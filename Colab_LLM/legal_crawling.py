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
MAX_TOTAL_COUNT = 15  # 중복제거 후 저장할 최대 건수
BATCH_SIZE = 10       # 한 번에 처리할 개수(페이지 단위)
BASE_URL = "http://www.yeslaw.com/lims/front/page/legalterm.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Referer": "http://www.yeslaw.com/lims/front/layout.html",
    "X-Requested-With": "XMLHttpRequest",
}

# ====== Pinecone/SBERT 관련 설정 ======
API_KEY = "pcsk_*****" # 마스킹 처리!
INDEX_NAME = "legal-index"
DIMENSION = 768
CLOUD = "aws"
REGION = "us-east-1"
PC_BATCH_SIZE = 100
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

def get_ids_all():
    """전체 용어 ID 리스트 추출 (pHangulPrefix=-1)"""
    params = {"pAct": "newList", "pHangulPrefix": "-1"}
    resp = requests.get(BASE_URL, headers=HEADERS, params=params)
    resp.raise_for_status()
    ids = resp.json().get("legaltermNo", [])
    print(f"\n가져온 전체 ID 개수: {len(ids)}")
    return ids

def get_word_and_html_by_id(lid):
    """ID로 word와 html 추출"""
    detail_params = {"pAct": "newView", "pLegaltermNo": lid}
    detail_resp = requests.get(BASE_URL, headers=HEADERS, params=detail_params)
    try:
        data = detail_resp.json().get("data", {})
        word = data.get("word")
        html = data.get("html")
    except Exception:
        word, html = None, None
    return word, html

def clean_html(html):
    """HTML 태그를 제거하고 텍스트만 반환"""
    if html is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator='\n').strip()

def load_existing_keywords(jsonl_paths):
    """기존 데이터의 모든 keyword를 dict(keyword -> set(files))로 반환 (중복 체크용)"""
    keyword_to_files = defaultdict(set)
    for path in jsonl_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    kw = item.get("keyword")
                    if isinstance(kw, list):
                        for k in kw:
                            keyword_to_files[k].add(path)
                    elif isinstance(kw, str):
                        keyword_to_files[kw].add(path)
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
        if fn.startswith("legal_data_crawling(") and fn.endswith(".jsonl")
    ]
    all_path = "legal_data.jsonl"
    if not os.path.exists(all_path):
        raise FileNotFoundError(f"{all_path} 파일이 반드시 필요합니다. 먼저 업로드 또는 생성하세요.")
    existing_jsonls.append(all_path)
    print("비교에 사용된 파일 목록:")
    for fname in existing_jsonls:
        print(f" - {fname}")

    keyword_to_files = load_existing_keywords(existing_jsonls)
    all_new_data = []
    duplicate_keywords = []
    theme_counts = {}
    ids = get_ids_all()

    total_count = 0
    page_index = 1
    total_processed = 0
    while total_processed < len(ids) and total_count < MAX_TOTAL_COUNT:
        batch = ids[total_processed:total_processed + BATCH_SIZE]
        print(f"\n=== [페이지 {page_index}] 법률정보 ===")
        print(f"  (리스트에서 추출된 용어 수: {len(batch)})")
        page_new_items = []
        for lid in batch:
            if total_count >= MAX_TOTAL_COUNT:
                break
            word, html = get_word_and_html_by_id(lid)
            keyword = word
            text = clean_html(html)
            text = clean_text(text)
            if not keyword or not text:
                continue
            is_duplicate = False
            if keyword in keyword_to_files:
                for dup_file in keyword_to_files[keyword]:
                    duplicate_keywords.append({"theme": "법률", "keyword": keyword, "file": dup_file})
                is_duplicate = True
            if is_duplicate:
                continue
            else:
                page_new_items.append({
                    "theme": "법률",
                    "keyword": [keyword],
                    "text": text
                })
                keyword_to_files[keyword].add("new_crawling")
                total_count += 1
            time.sleep(0.1)
        print(f"  (중복 제거 후 실제 저장 건수: {len(page_new_items)})")
        all_new_data.extend(page_new_items)
        theme_counts["법률"] = theme_counts.get("법률", 0) + len(page_new_items)
        page_index += 1
        total_processed += BATCH_SIZE

    jsonl_path = get_next_filename("legal_data_crawling")
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
            count = counter.get("법률", 0)
            print(f"    - 법률: {count}개")
        print("\n테마별로 총 걸러진 keyword 개수:")
        count = total_theme_count.get("법률", 0)
        print(f"  - 법률: {count}개")
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
        for k in range(0, len(vectors), PC_BATCH_SIZE):
            upsert_batch = vectors[k:k+PC_BATCH_SIZE]
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
        for k in range(0, len(vectors), PC_BATCH_SIZE):
            upsert_batch = vectors[k:k+PC_BATCH_SIZE]
            index.upsert(upsert_batch)
    print("keyword 벡터 업서트 완료")
    print("전체 벡터 업서트가 끝났습니다!")

if __name__ == "__main__":
    # 1. 크롤링 및 신규 데이터 저장 & Drive로 복사
    jsonl_path = crawl_and_save_new_jsonl()
    # 2. Pinecone 임베딩 및 업서트
    pinecone_upsert_from_jsonl(jsonl_path)