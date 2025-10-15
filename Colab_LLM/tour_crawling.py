import os
import json
import requests
from collections import defaultdict, Counter
import re
import hashlib
import shutil
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

# ====== 크롤러 관련 설정 ======
SERVICE_KEY = "*****" # 마스킹 처리!
MOBILE_APP = "AppTest"
MOBILE_OS = "ETC"
AREA_URL = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"
DETAIL_URL = "http://apis.data.go.kr/B551011/KorService2/detailCommon2"
NUM_OF_ROWS = 10
MAX_PER_THEME = 5

# THEMES에 display_name을 추가
THEMES = [
    {"name": "자연관광지", "cat1": "A01", "cat2": "A0101", "contentTypeId": 12, "display_name": "자연관광정보"},
    {"name": "역사관광지", "cat1": "A02", "cat2": "A0201", "contentTypeId": 12, "display_name": "역사관광정보"},
    {"name": "문화시설",   "cat1": "A02", "cat2": "A0206", "contentTypeId": 14, "display_name": "문화관광정보"},
]

# ====== Pinecone/SBERT 관련 설정 ======
API_KEY = "pcsk_*****" # 마스킹 처리!
INDEX_NAME = "tour-index"
DIMENSION = 768
CLOUD = "aws"
REGION = "us-east-1"
BATCH_SIZE = 100  # Pinecone upsert 배치
SBERT_BATCH_SIZE = 64

def safe_id(s):
    if isinstance(s, str):
        try:
            s.encode("ascii")
            return s
        except UnicodeEncodeError:
            return hashlib.md5(s.encode("utf-8")).hexdigest()
    else:
        return str(s)

def get_tour_list_page(cat1, cat2, content_type_id=12, num_of_rows=NUM_OF_ROWS, page_no=1):
    params = {
        "serviceKey": SERVICE_KEY,
        "MobileApp": MOBILE_APP,
        "MobileOS": MOBILE_OS,
        "contentTypeId": content_type_id,
        "cat1": cat1,
        "cat2": cat2,
        "numOfRows": num_of_rows,
        "pageNo": page_no,
        "arrange": "C",
        "_type": "json"
    }
    resp = requests.get(AREA_URL, params=params)
    try:
        data = resp.json()
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not items or isinstance(items, str):
            return []
        return items
    except Exception as e:
        print("API 응답 파싱 오류:", e)
        print("원본 응답:", resp.text)
        return []

def get_detail_overview(contentid):
    params = {
        "serviceKey": SERVICE_KEY,
        "MobileApp": MOBILE_APP,
        "MobileOS": MOBILE_OS,
        "contentId": contentid,
        "_type": "json"
    }
    resp = requests.get(DETAIL_URL, params=params)
    try:
        data = resp.json()
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", {})
        if isinstance(items, list):
            for item in items:
                if "overview" in item:
                    return item["overview"]
            return ""
        return items.get("overview", "")
    except Exception as e:
        print(f"상세정보 파싱 오류(contentid={contentid}):", e)
        print("원본 응답:", resp.text)
        return ""

def load_existing_keywords(jsonl_paths):
    keyword_to_files = defaultdict(set)
    for path in jsonl_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    for kw in item.get("keyword", []):
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
        if fn.startswith("tour_data_crawling(") and fn.endswith(".jsonl")
    ]
    all_path = "tour_data_all.jsonl"
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
    for theme in THEMES:
        theme_new_items = []
        page_no = 1
        display_name = theme.get("display_name", f"{theme['name']}관광정보")
        while len(theme_new_items) < MAX_PER_THEME:
            print()
            tour_list = get_tour_list_page(theme["cat1"], theme["cat2"], theme["contentTypeId"], num_of_rows=NUM_OF_ROWS, page_no=page_no)
            print(f"=== [페이지 {page_no}] {display_name} ===")
            print(f"  (리스트에서 추출된 {theme['name']} 수: {len(tour_list)})")
            before_save_count = len(theme_new_items)
            for tour in tour_list:
                if len(theme_new_items) >= MAX_PER_THEME:
                    break
                title = tour.get("title", "")
                contentid = tour.get("contentid", "")
                overview = tour.get("overview", "")
                image = tour.get("firstimage", "")
                if not image:
                    continue
                if not overview:
                    overview = get_detail_overview(contentid)
                if not title or not overview:
                    continue
                keyword_list = [title]
                for kw in keyword_list:
                    if kw in keyword_to_files:
                        for dup_file in keyword_to_files[kw]:
                            duplicate_keywords.append({"theme": theme["name"], "keyword": kw, "file": dup_file})
                        break
                else:
                    theme_new_items.append({
                        "theme": theme["name"],
                        "keyword": keyword_list,
                        "text": overview
                    })
                    for kw in keyword_list:
                        keyword_to_files[kw].add("new_crawling")
            after_save_count = len(theme_new_items)
            print(f"  (중복 제거 후 실제 저장 건수: {after_save_count - before_save_count})")
            if not tour_list:
                print(f"  (더 이상 데이터 없음 또는 API 오류, 채운 개수: {len(theme_new_items)})")
                break
            page_no += 1
        all_new_data.extend(theme_new_items)
        theme_counts[theme['name']] = len(theme_new_items)
    jsonl_path = get_next_filename("tour_data_crawling")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for item in all_new_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print()
    print(f"신규 데이터 {len(all_new_data)}건 저장: {jsonl_path}")
    print("테마별 신규 데이터 건수:", theme_counts)
    print()
    print("중복되어서 걸러진 keyword 개수 (파일별/테마별):")
    if duplicate_keywords:
        dup_count = defaultdict(lambda: Counter())
        total_theme_count = Counter()
        for dup in duplicate_keywords:
            dup_count[dup["file"]][dup["theme"]] += 1
            total_theme_count[dup["theme"]] += 1
        for file_name, counter in dup_count.items():
            print(f"  파일: {file_name}")
            for theme in THEMES:
                tname = theme["name"]
                count = counter.get(tname, 0)
                print(f"    - {tname}: {count}개")
        print("\n테마별로 총 걸러진 keyword 개수:")
        for theme in THEMES:
            tname = theme["name"]
            count = total_theme_count.get(tname, 0)
            print(f"  - {tname}: {count}개")
    else:
        print(" (중복된 keyword 없음)")
    
    # ====== 생성된 파일을 드라이브로 복사 ======
    drive_path = "/content/drive/MyDrive/"
    target_path = os.path.join(drive_path, jsonl_path)
    try:
        shutil.copy(jsonl_path, target_path)
        print(f"✅ 파일이 Drive로 복사되었습니다: {target_path}")
    except Exception as e:
        print(f"❌ Drive 복사 실패: {e}")

    return jsonl_path

def pinecone_upsert_from_jsonl(jsonl_path):
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
            # 각각의 keyword마다 전체 text를 context로 저장
            vector_id = f"ctx_{doc_id}_{safe_id(kw)}_0"
            context_items.append({
                "vector_id": vector_id,
                "context": text,    # 전체 본문을 context로!
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
    # 1. 크롤링 및 신규 데이터 저장
    jsonl_path = crawl_and_save_new_jsonl()
    # 2. Pinecone 임베딩 및 업서트
    pinecone_upsert_from_jsonl(jsonl_path)