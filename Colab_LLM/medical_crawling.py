import os
import json
import requests
import time
import re
import hashlib
import shutil
from collections import defaultdict, Counter
from bs4 import BeautifulSoup

# ====== 크롤링 설정값 ======
MAX_TOTAL_COUNT = 15  # 전체 수집할 데이터 개수
BASE_LIST_URL = "https://www.snuh.org/health/nMedInfo/nList.do?pageIndex={page}&sortType=&searchNWord=&searchKey="

# ====== Pinecone/SBERT 관련 설정 ======
API_KEY = "pcsk_*****" # 마스킹 처리!
INDEX_NAME = "medical-index"
DIMENSION = 768
CLOUD = "aws"
REGION = "us-east-1"
BATCH_SIZE = 100
SBERT_BATCH_SIZE = 64

DRIVE_PATH = "/content/drive/MyDrive/"

def safe_id(s):
    if isinstance(s, str):
        try:
            s.encode("ascii")
            return s
        except UnicodeEncodeError:
            return hashlib.md5(s.encode("utf-8")).hexdigest()
    else:
        return str(s)

def clean_text(text):
    """
    텍스트에서 줄바꿈 문자(\r, \n 등)를 모두 공백으로 치환하고, 여러 공백은 하나로 합침
    """
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text

def get_medical_list_page(page=1):
    """리스트 페이지에서 각 질병의 medid, 한글명 추출"""
    url = BASE_LIST_URL.format(page=page)
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for div_item in soup.select("div.thumbType04 div.txtWrap div.title a"):
        href = div_item.get("href")
        m = re.search(r"medid=([A-Za-z0-9]+)", href or "")
        medid = m.group(1) if m else None

        strong = div_item.find("strong")
        if strong:
            title_text = strong.text.strip()
            m2 = re.match(r"([^\[]+)\s*\[([^\]]+)\]", title_text)
            if m2:
                korean_name = m2.group(1).strip()
            else:
                korean_name = title_text
            items.append({
                "medid": medid,
                "keyword": korean_name
            })
    return items

def get_medical_detail(medid, page_index="1"):
    """상세페이지에서 질병명(한글)과 정의의 두 번째 단락까지 추출, 줄바꿈 없이 저장"""
    url = "https://www.snuh.org/health/nMedInfo/nView.do"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://www.snuh.org/health/nMedInfo/nList.do?pageIndex={page_index}"
    }
    data = {
        "searchNWord": "",
        "sortType": "",
        "pageIndex": str(page_index),
        "searchKey": "",
        "medid": medid
    }
    resp = requests.post(url, headers=headers, data=data)
    soup = BeautifulSoup(resp.text, "html.parser")
    # 질병명 (한글)
    title_div = soup.find("div", class_="viewTitle")
    keyword = None
    if title_div:
        h3 = title_div.find("h3")
        if h3:
            full_title = h3.text.strip()
            m = re.match(r"([^\[]+)\s*\[([^\]]+)\]", full_title)
            if m:
                keyword = m.group(1).strip()
            else:
                keyword = full_title
    # 정의(설명) - '정의' 항목만 추출
    desc_div = soup.find("div", class_="viewContent")
    definition_text = ""
    if desc_div:
        h5_def = desc_div.find("h5", string=re.compile("정의"))
        if h5_def:
            p_def = h5_def.find_next_sibling("p")
            if p_def:
                definition_text = p_def.get_text(strip=True)
        if not definition_text and h5_def:
            p_def = h5_def.find_next("p")
            if p_def:
                definition_text = p_def.get_text(strip=True)
    if definition_text:
        paragraphs = definition_text.split('\r\n\r\n')
        definition_text = '\r\n\r\n'.join(paragraphs[:2]).strip()
        definition_text = clean_text(definition_text)
    return {
        "keyword": keyword,
        "text": definition_text
    }

def load_existing_keywords(jsonl_paths):
    """기존 데이터의 모든 keyword(한글명, 배열 포함)를 dict(keyword -> set(files))로 반환 (중복 체크용)"""
    keyword_to_files = defaultdict(set)
    for path in jsonl_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    kws = item.get("keyword")
                    if isinstance(kws, list):
                        for kw in kws:
                            keyword_to_files[kw].add(path)
                    elif isinstance(kws, str):
                        keyword_to_files[kws].add(path)
                except Exception:
                    continue
    return keyword_to_files

def get_next_filename(prefix):
    idx = 1
    while True:
        fname = f"{prefix}({idx}).jsonl"
        if not os.path.exists(fname):
            return fname
        idx += 1

def crawl_and_save_new_jsonl():
    existing_jsonls = [
        fn for fn in os.listdir()
        if fn.startswith("medical_data_crawling(") and fn.endswith(".jsonl")
    ]
    all_path = "medical_data.jsonl"
    if not os.path.exists(all_path):
        raise FileNotFoundError(f"{all_path} 파일이 반드시 필요합니다. 먼저 업로드 또는 생성하세요.")
    existing_jsonls.append(all_path)
    print("비교에 사용된 파일 목록:")
    for fname in existing_jsonls:
        print(f" - {fname}")
    keyword_to_files = load_existing_keywords(existing_jsonls)
    duplicate_keywords = []
    all_new_data = []
    theme_counts = {}
    total_count = 0
    page_index = 1
    while total_count < MAX_TOTAL_COUNT:
        print(f"\n=== [페이지 {page_index}] 의료정보 ===")
        items = get_medical_list_page(page_index)
        print(f"  (리스트에서 추출된 질병 수: {len(items)})")
        page_new_items = []
        for item in items:
            if total_count >= MAX_TOTAL_COUNT:
                break
            medid = item['medid']
            data = get_medical_detail(medid, page_index=str(page_index))
            new_kws = data["keyword"]
            is_duplicate = False
            if isinstance(new_kws, list):
                for kw in new_kws:
                    if kw and kw in keyword_to_files:
                        for dup_file in keyword_to_files[kw]:
                            duplicate_keywords.append({"theme": "의료", "keyword": kw, "file": dup_file})
                        is_duplicate = True
                        break
            elif isinstance(new_kws, str):
                if new_kws and new_kws in keyword_to_files:
                    for dup_file in keyword_to_files[new_kws]:
                        duplicate_keywords.append({"theme": "의료", "keyword": new_kws, "file": dup_file})
                    is_duplicate = True
            if is_duplicate:
                continue
            else:
                if data["text"]:
                    page_new_items.append({
                        "theme": "의료",
                        "keyword": [new_kws] if isinstance(new_kws, str) else (new_kws if new_kws else []),
                        "text": data["text"]
                    })
                    kws_to_add = [new_kws] if isinstance(new_kws, str) else (new_kws if new_kws else [])
                    for kw in kws_to_add:
                        if kw:
                            keyword_to_files[kw].add("new_crawling")
                    total_count += 1
                time.sleep(0.5)
        print(f"  (중복 제거 후 실제 저장 건수: {len(page_new_items)})")
        all_new_data.extend(page_new_items)
        theme_counts["의료"] = theme_counts.get("의료", 0) + len(page_new_items)
        page_index += 1
    jsonl_path = get_next_filename("medical_data_crawling")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for item in all_new_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"\n신규 데이터 {len(all_new_data)}건 저장: {jsonl_path}")
    print("테마별 신규 데이터 건수:", theme_counts)
    print("\n중복되어서 걸러진 keyword 개수 (파일별/테마별):")
    if duplicate_keywords:
        dup_count = defaultdict(lambda: Counter())
        total_theme_count = Counter()
        for dup in duplicate_keywords:
            dup_count[dup["file"]][dup["theme"]] += 1
            total_theme_count[dup["theme"]] += 1
        for file_name, counter in dup_count.items():
            print(f"  파일: {file_name}")
            count = counter.get("의료", 0)
            print(f"    - 의료: {count}개")
        print("\n테마별로 총 걸러진 keyword 개수:")
        count = total_theme_count.get("의료", 0)
        print(f"  - 의료: {count}개")
    else:
        print(" (중복된 keyword 없음)")

    # ====== 파일을 Drive로 복사 ======
    target_path = os.path.join(DRIVE_PATH, jsonl_path)
    try:
        shutil.copy(jsonl_path, target_path)
        print(f"✅ 파일이 Drive로 복사되었습니다: {target_path}")
    except Exception as e:
        print(f"❌ Drive 복사 실패: {e}")

    return jsonl_path

def pinecone_upsert_from_jsonl(jsonl_path):
    from pinecone import Pinecone, ServerlessSpec
    from sentence_transformers import SentenceTransformer

    print("\nPinecone 인스턴스 생성")
    pc = Pinecone(api_key=API_KEY)
    print("인덱스 존재 여부 확인 및 생성")
    if INDEX_NAME not in pc.list_indexes().names():
        print("인덱스가 존재하지 않아 새로 생성합니다.")
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud=CLOUD, region=REGION)
        )
    else:
        print("인덱스가 이미 존재합니다.")
    print("인덱스 연결 중")
    index = pc.Index(INDEX_NAME)
    print("SBERT 모델 로딩 시작")
    SBERT_MODEL = SentenceTransformer("snunlp/KR-SBERT-V40K-klueNLI-augSTS")
    print("SBERT 모델 로딩 완료")
    documents = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            item = json.loads(line)
            doc_text = item.get("text", "")
            doc_text = clean_text(doc_text)
            doc_keyword = item.get("keyword", [])
            doc_id = f"{jsonl_path.split('/')[-1]}_{i}"
            if isinstance(doc_keyword, list):
                doc_keyword = list(set(doc_keyword))
            elif isinstance(doc_keyword, str):
                doc_keyword = [doc_keyword]
            documents.append({
                "id": doc_id,
                "text": doc_text,
                "keyword": doc_keyword
            })
    print(f"전체 문서 수: {len(documents)}")
    # 전체 text를 하나의 context로 저장 (keyword별로)
    context_items = []
    for doc_idx, doc in enumerate(documents):
        doc_id = doc["id"]
        text = doc["text"]
        keywords = doc["keyword"]
        for kw in keywords:
            vector_id = f"ctx_{doc_id}_{safe_id(kw)}_0"
            context_items.append({
                "vector_id": vector_id,
                "context": text,
                "keyword": kw,
                "doc_id": doc_id
            })
    print(f"context 벡터 수: {len(context_items)}")

    all_keywords = set()
    for doc in documents:
        for kw in doc["keyword"]:
            all_keywords.add(kw)
    keyword_items = []
    for kw in all_keywords:
        vector_id = f"kw_{safe_id(kw)}"
        keyword_items.append({
            "vector_id": vector_id,
            "keyword": kw
        })
    print(f"keyword 벡터 수: {len(keyword_items)}")
    print("context 벡터 업서트 시작")
    for i in range(0, len(context_items), SBERT_BATCH_SIZE):
        batch_items = context_items[i:i+SBERT_BATCH_SIZE]
        print(f"[context] 업서트: {i} ~ {i+len(batch_items)-1} / {len(context_items)}")
        batch_contexts = [item["context"] for item in batch_items]
        batch_embeddings = SBERT_MODEL.encode(batch_contexts, batch_size=SBERT_BATCH_SIZE, show_progress_bar=False)
        vectors = []
        for j, item in enumerate(batch_items):
            vectors.append((
                item["vector_id"],
                batch_embeddings[j].tolist(),
                {
                    "type": "context",
                    "context": item["context"],
                    "keyword": item["keyword"],
                    "doc_id": item["doc_id"]
                }
            ))
        for k in range(0, len(vectors), BATCH_SIZE):
            upsert_batch = vectors[k:k+BATCH_SIZE]
            index.upsert(upsert_batch)
    print("context 벡터 업서트 완료")
    print("keyword 벡터 업서트 시작")
    for i in range(0, len(keyword_items), SBERT_BATCH_SIZE):
        batch_items = keyword_items[i:i+SBERT_BATCH_SIZE]
        print(f"[keyword] 업서트: {i} ~ {i+len(batch_items)-1} / {len(keyword_items)}")
        batch_keywords = [item["keyword"] for item in batch_items]
        batch_embeddings = SBERT_MODEL.encode(batch_keywords, batch_size=SBERT_BATCH_SIZE, show_progress_bar=False)
        vectors = []
        for j, item in enumerate(batch_items):
            vectors.append((
                item["vector_id"],
                batch_embeddings[j].tolist(),
                {
                    "type": "keyword",
                    "keyword": item["keyword"]
                }
            ))
        for k in range(0, len(vectors), BATCH_SIZE):
            upsert_batch = vectors[k:k+BATCH_SIZE]
            index.upsert(upsert_batch)
    print("keyword 벡터 업서트 완료")
    print("전체 벡터 업서트가 끝났습니다!")

if __name__ == "__main__":
    # 1. 크롤링 및 신규 데이터 저장 & Drive로 복사
    jsonl_path = crawl_and_save_new_jsonl()
    # 2. Pinecone 임베딩 및 업서트
    pinecone_upsert_from_jsonl(jsonl_path)