import warnings
import torch
import re
import subprocess
import logging
import time
from difflib import SequenceMatcher
from flask import Flask, request, jsonify
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from kiwipiepy import Kiwi
from sentence_transformers import SentenceTransformer, util
from pinecone import Pinecone
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- 주제별 인덱스/어댑터/프롬프트 설정 ---
DOMAIN_CONFIG = {
    "관광및지역자원": {
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "tour-index",
        "lora_adapter_path": "./tour_data_all_adapter",
        "prompt_template": "다음 관광 문서에서 '{keywords}'와 관련된 핵심 키워드를 추출해주세요."
    },
    "의학및의료정보": {
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "medical-index",
        "lora_adapter_path": "./medical_data_adapter",
        "prompt_template": "다음 의료 문서에서 '{keywords}'와 관련된 핵심 키워드를 추출해주세요."
    },
    "법률및행정": {
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "legal-index",
        "lora_adapter_path": "./legal_data_adapter",
        "prompt_template": "다음 법률 문서에서 '{keywords}'와 관련된 핵심 키워드를 추출해주세요."
    }
}
BASE_MODEL = "EleutherAI/polyglot-ko-1.3b"
MAX_DOCS = 5
PINECONE_TOP_K = 10
MAX_FINAL_KEYWORDS = 5
MAX_CONTEXTS_PER_DOC = 3  # 상위 3개 context만 사용

print("🔵 Loading base tokenizer and model...")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, padding_side="left")
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
print("🟢 Base tokenizer loaded.")

# 카테고리별 모델 캐싱 (base_model + LoRA adapter) - 서버 시작 시 미리 모두 올림
category_model_cache = {}

def build_category_model_cache():
    print("\n🚀 모든 카테고리별 base+LoRA 모델 캐시 생성 시작...\n")
    for category, config in DOMAIN_CONFIG.items():
        print(f"🚀 [{category}] LoRA 어댑터 적용 모델 생성 중...")
        model_for_adapter = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True
        )
        lora_model = PeftModel.from_pretrained(model_for_adapter, config["lora_adapter_path"])
        lora_model.eval()
        category_model_cache[category] = (tokenizer, lora_model)
        print(f"✅ [{category}] LoRA 어댑터 적용 완료 및 캐시됨.\n")

def get_model_and_tokenizer(category):
    return category_model_cache.get(category, (None, None))

warnings.filterwarnings("ignore", category=FutureWarning)
SBERT_MODEL = SentenceTransformer("snunlp/KR-SBERT-V40K-klueNLI-augSTS")
kiwi = Kiwi()

def pinecone_query_contexts(query_text, config, top_k=PINECONE_TOP_K):
    pc = Pinecone(api_key=config["pinecone_api_key"])
    index = pc.Index(config["pinecone_index_name"])
    query_emb = SBERT_MODEL.encode(query_text, convert_to_tensor=False).tolist()
    result = index.query(
        vector=query_emb,
        top_k=top_k,
        include_metadata=True,
        filter={"type": "context"}
    )
    return result['matches']

def pinecone_query_keywords(query_text, config, top_k=PINECONE_TOP_K, threshold=0.65):
    pc = Pinecone(api_key=config["pinecone_api_key"])
    index = pc.Index(config["pinecone_index_name"])
    query_emb = SBERT_MODEL.encode(query_text, convert_to_tensor=False).tolist()
    result = index.query(
        vector=query_emb,
        top_k=top_k * 10,
        include_metadata=True,
        filter={"type": "keyword"}
    )
    matches = [
        match for match in result['matches']
        if match.get('score', 0) >= threshold
    ]
    matches.sort(key=lambda m: m.get('score', 0), reverse=True)
    keywords = []
    seen_norm = set()
    for match in matches:
        meta = match.get('metadata', {})
        kw = meta.get('keyword')
        if not kw:
            continue
        norm_kw = kw.replace(" ", "").lower()
        if norm_kw not in seen_norm:
            keywords.append(kw)
            seen_norm.add(norm_kw)
        if len(keywords) >= top_k:
            break
    return keywords

def keyword_exists_in_pinecone(keyword, config):
    pc = Pinecone(api_key=config["pinecone_api_key"])
    index = pc.Index(config["pinecone_index_name"])
    query_emb = SBERT_MODEL.encode(keyword, convert_to_tensor=False).tolist()
    result = index.query(
        vector=query_emb,
        top_k=1,
        include_metadata=True,
        filter={"type": "keyword"}
    )
    for match in result["matches"]:
        meta = match.get("metadata", {})
        if meta.get("keyword") == keyword:
            return True
    return False

def parallel_pinecone_query_contexts(all_keywords, config, top_k=PINECONE_TOP_K):
    results = {}
    with ThreadPoolExecutor() as executor:
        future_to_kw = {executor.submit(pinecone_query_contexts, kw, config, top_k): kw for kw in all_keywords}
        for future in as_completed(future_to_kw):
            kw = future_to_kw[future]
            try:
                matches = future.result()
                results[kw] = matches
            except Exception:
                results[kw] = []
    return results

def batch_generate_keywords(batch_prompts, model, tokenizer):
    inputs = tokenizer(batch_prompts, return_tensors="pt", padding=True, truncation=True, max_length=2048).to(model.device)
    outputs = model.generate(
        input_ids=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        max_new_tokens=150,
        temperature=0.95,
        top_p=0.92,
        top_k=40,
        repetition_penalty=1.1,
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )
    results = []
    for i, output in enumerate(outputs):
        full_text = tokenizer.decode(output, skip_special_tokens=True)
        generated_text = full_text[len(batch_prompts[i]):].strip()
        kws = [kw.strip() for kw in re.split(r"[,\n]", generated_text) if kw.strip()]
        results.append(kws)
    return results

def postprocess_keywords_with_kiwi(raw_keywords, reference_keywords=None, max_final_keywords=MAX_FINAL_KEYWORDS):
    t0 = time.time()
    def extract_nouns(text):
        tokens = kiwi.tokenize(text)
        return [t.form for t in tokens if 'N' in t.tag and 2 <= len(t.form) <= 5]

    def is_similar(kw1, kw2, threshold=0.65):
        return SequenceMatcher(None, kw1, kw2).ratio() >= threshold

    def contains_invalid_pos(text):
        try:
            analyzed = kiwi.analyze(text)[0][0]
            for _, pos, *_ in analyzed:
                if pos.startswith(('J', 'E', 'V', 'X')):
                    return True
        except:
            return False
        return False

    def generate_ngram_candidates(nouns, raw_text):
        candidates = []
        for n in range(2, 4):
            for i in range(len(nouns) - n + 1):
                chunk = nouns[i:i + n]
                if all(2 <= len(word) <= 5 for word in chunk):
                    phrase = "".join(chunk)
                    if phrase in raw_text:
                        candidates.append(phrase)
        return candidates

    candidate_kw_list = []
    kw_to_candidates = []
    for kw in raw_keywords:
        cleaned_text = re.sub(r"[^\w가-힣]", " ", kw).strip()
        nouns = extract_nouns(cleaned_text)
        if not nouns:
            kw_to_candidates.append([])
            continue
        joined_candidates = [" ".join(nouns)]
        joined_candidates.extend(generate_ngram_candidates(nouns, kw))
        joined_candidates = list(dict.fromkeys(joined_candidates))
        kw_to_candidates.append(joined_candidates)
        candidate_kw_list.extend(joined_candidates)
    candidate_kw_list = list(dict.fromkeys(candidate_kw_list))

    ref_keywords = reference_keywords if reference_keywords else []
    ref_embeddings = SBERT_MODEL.encode(ref_keywords, convert_to_tensor=True) if ref_keywords else None
    candidate_embeddings = SBERT_MODEL.encode(candidate_kw_list, convert_to_tensor=True) if candidate_kw_list else None

    def is_semantically_unrelated_to_all_batch(candidate_idx, threshold=0.45):
        if ref_embeddings is None or candidate_embeddings is None:
            return False
        cand_emb = candidate_embeddings[candidate_idx]
        similarities = util.pytorch_cos_sim(cand_emb.unsqueeze(0), ref_embeddings)
        if (similarities >= threshold).any():
            return False
        return True

    def is_prefix_duplicate(joined, seen):
        prefix = joined.split()[0]
        return any(prev.startswith(prefix) for prev in seen)

    def is_meaningless(kw, candidate_idx):
        tokens = kw.split()
        if any(char.isdigit() for char in kw):
            return True
        if kw.startswith("키워드 "):
            return True
        if len(tokens) == 1 and len(tokens[0]) <= 2:
            return True
        for i in range(len(tokens)):
            for j in range(i + 1, len(tokens)):
                if tokens[i] in tokens[j] or tokens[j] in tokens[i]:
                    return True
        if contains_invalid_pos(kw):
            return True
        if is_semantically_unrelated_to_all_batch(candidate_idx):
            return True
        return False

    cleaned, seen, backup_candidates = [], [], []
    norm_seen = set()
    for kw_candidates in kw_to_candidates:
        for joined in kw_candidates:
            if reference_keywords and any(joined.replace(" ", "") == ref_kw.replace(" ", "") for ref_kw in reference_keywords):
                continue
            candidate_idx = candidate_kw_list.index(joined)
            if is_meaningless(joined, candidate_idx) or is_prefix_duplicate(joined, seen):
                continue
            tokens = joined.split()
            if not (2 <= len(tokens) <= 3):
                continue
            if any(len(t) < 2 or len(t) > 5 for t in tokens):
                continue
            norm_joined = joined.replace(" ", "").lower()
            if norm_joined in norm_seen:
                continue
            if not any(is_similar(joined, prev) for prev in seen):
                seen.append(joined)
                cleaned.append(joined)
                norm_seen.add(norm_joined)
            else:
                backup_candidates.append(joined)
            if len(cleaned) >= max_final_keywords:
                break
        if len(cleaned) >= max_final_keywords:
            break

    if len(cleaned) < max_final_keywords:
        for backup in backup_candidates:
            norm_backup = backup.replace(" ", "").lower()
            if norm_backup not in norm_seen:
                cleaned.append(backup)
                norm_seen.add(norm_backup)
            if len(cleaned) >= max_final_keywords:
                break

    def sort_by_sbert_similarity(keywords, reference_keywords):
        if not keywords or not reference_keywords:
            return [(kw, None) for kw in keywords]
        key_embs = SBERT_MODEL.encode(keywords, convert_to_tensor=True)
        ref_embs = SBERT_MODEL.encode(reference_keywords, convert_to_tensor=True)
        scores = []
        sims = util.pytorch_cos_sim(key_embs, ref_embs)
        for i, sim_row in enumerate(sims):
            max_sim = sim_row.max().item()
            scores.append((keywords[i], max_sim))
        sorted_keywords = sorted(scores, key=lambda x: x[1], reverse=True)
        return sorted_keywords

    sorted_cleaned = sort_by_sbert_similarity(cleaned, reference_keywords)
    print(f"[타이밍] postprocess_keywords_with_kiwi: {time.time() - t0:.2f}초 소요")
    return sorted_cleaned[:max_final_keywords]

app = Flask(__name__)

@app.route("/mindmap", methods=["POST"])
def mindmap():
    all_t0 = time.time()
    data = request.json
    keyword = data.get("keyword", "").strip()
    category = data.get("category")  # 프론트에서 전달된 category

    config = DOMAIN_CONFIG.get(category)
    print(f"\n📢 프론트에서 전달받은 category: '{category}'")
    if config is None:
        print(f"❌ DOMAIN_CONFIG에서 해당 category를 찾지 못함: '{category}'")
        return jsonify({"error": f"지원하지 않는 주제입니다: {category}"}), 400
    else:
        print(f"✅ DOMAIN_CONFIG에서 선택된 주제 설정: {category}")
        print(f"    🟡 pinecone_index_name: {config['pinecone_index_name']}")
        print(f"    🟢 lora_adapter_path: {config['lora_adapter_path']}")

    # 카테고리별 모델/어댑터 캐싱 사용
    tokenizer, lora_model = get_model_and_tokenizer(category)
    if tokenizer is None or lora_model is None:
        print("❌ 모델/어댑터 캐싱 실패")
        return jsonify({"keywords": []}), 500

    # Pinecone, 프롬프트, etc 모두 config에서 꺼냄
    t0 = time.time()
    pinecone_check = keyword_exists_in_pinecone(keyword, config)
    if pinecone_check:
        print(f"\n📌 입력 키워드: ['{keyword}']")
    else:
        print(f"\n⚠️ 입력 키워드 '{keyword}'는 존재하지 않으므로 제외")
    print(f"[타이밍] keyword_exists_in_pinecone: {time.time() - t0:.2f}초 소요")
    base_keywords = [keyword] if pinecone_check else []

    # 유사 키워드 추출 및 타이밍 로그
    t0 = time.time()
    similar_keywords_raw = pinecone_query_keywords(keyword, config, top_k=PINECONE_TOP_K)
    similar_keywords = [kw for kw in similar_keywords_raw if kw != keyword]
    print(f"📌 유사 키워드: {similar_keywords}")
    print(f"[타이밍] pinecone_query_keywords: {time.time() - t0:.2f}초 소요")

    all_keywords = base_keywords + [kw for kw in similar_keywords if kw not in base_keywords]
    print(f"🔍 전체 검색 키워드: {all_keywords}")

    t0 = time.time()
    context_results = parallel_pinecone_query_contexts(all_keywords, config, top_k=PINECONE_TOP_K)
    doc_scores = {}
    context_by_doc = {}

    # context를 (context, score) 튜플로 저장
    for kw, matches in context_results.items():
        for match in matches:
            meta = match.get('metadata', {})
            doc_id = meta.get('doc_id') or meta.get('document_id') or meta.get('id')
            ctx = meta.get('context')
            score = match.get('score', 0)
            if doc_id and ctx:
                if doc_id not in doc_scores or score > doc_scores[doc_id]:
                    doc_scores[doc_id] = score
                context_by_doc.setdefault(doc_id, []).append((ctx, score))

    sorted_doc_ids = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)
    doc_ids = sorted_doc_ids[:MAX_DOCS]
    total_docs = len(doc_ids)
    print(f"\n🔎 전체 검색 키워드 기준 임베딩 유사도가 높은 문서 총 {total_docs}건")
    print(f"[타이밍] parallel_pinecone_query_contexts: {time.time() - t0:.2f}초 소요")

    if total_docs == 0:
        print("❗ 관련 문서를 찾지 못했습니다.")
        print(f"[타이밍] 전체 요청: {time.time() - all_t0:.2f}초 소요")
        return jsonify({"keywords": []})

    batch_prompts = []
    for idx, doc_id in enumerate(doc_ids):
        contexts_and_scores = context_by_doc.get(doc_id, [])
        if not contexts_and_scores:
            continue
        # 점수 기준 내림차순 정렬 후 상위 3개 추출
        sorted_contexts = sorted(contexts_and_scores, key=lambda x: x[1], reverse=True)
        top_contexts = [ctx for ctx, score in sorted_contexts[:MAX_CONTEXTS_PER_DOC]]
        print(f"📄 [{idx + 1}/{total_docs}] 문서 처리 중... (doc_id: {doc_id}, score: {doc_scores[doc_id]:.4f}, contexts: {len(top_contexts)})")
        keywords_str = ", ".join(all_keywords)
        prompt = (
            config["prompt_template"].format(keywords=keywords_str)
            + "\n\n" + "\n\n".join(top_contexts)
            + "\n\n키워드:"
        )
        batch_prompts.append(prompt)

    if not batch_prompts:
        print("❗ 추출할 문서가 없습니다.")
        print(f"[타이밍] 전체 요청: {time.time() - all_t0:.2f}초 소요")
        return jsonify({"keywords": []})

    t0 = time.time()
    batch_keywords = batch_generate_keywords(batch_prompts, lora_model, tokenizer)
    print(f"[타이밍] batch_generate_keywords (LoRA 생성): {time.time() - t0:.2f}초 소요")
    all_extracted_keywords = [kw for kws in batch_keywords for kw in kws]
    reference_keywords = all_keywords
    t0 = time.time()
    final_keywords = postprocess_keywords_with_kiwi(
        all_extracted_keywords,
        reference_keywords=reference_keywords,
        max_final_keywords=MAX_FINAL_KEYWORDS
    )
    print(f"[타이밍] postprocess_keywords_with_kiwi (최종후처리): {time.time() - t0:.2f}초 소요")

    norm_input_kw = keyword.replace(" ", "")
    # 유사도와 함께 콘솔 출력용
    keywords_with_sim = [
        {"keyword": kw, "similarity": round(sim, 4) if sim is not None else None}
        for kw, sim in final_keywords if kw.replace(" ", "") != norm_input_kw
    ]
    # 실제 API 반환은 키워드만 리스트로!
    keywords_only = [
        kw for kw, sim in final_keywords if kw.replace(" ", "") != norm_input_kw
    ]

    # Colab(콘솔)에서는 키워드 (유사도) 형식으로 출력
    print("\n✅ 실제 API 반환 키워드:")
    for item in keywords_with_sim:
        display_str = f"{item['keyword']} ({item['similarity']})" if item['similarity'] is not None else item['keyword']
        print(f"📌 {display_str}")

    print(f"[타이밍] 전체 요청: {time.time() - all_t0:.2f}초 소요")
    return jsonify({"keywords": keywords_only[:MAX_FINAL_KEYWORDS]})

if __name__ == "__main__":
    build_category_model_cache()
    print("✅ 모든 카테고리 모델 캐시 완료!")

    tunnel = subprocess.Popen(
        ['npx', 'localtunnel', '--port', '5001', '--subdomain', 'mind-road'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    public_url = None
    for i in range(30):
        line = tunnel.stdout.readline()
        if 'your url is:' in line:
            public_url = line.split('your url is:')[1].strip()
            print(f"\n🔗 Localtunnel public URL: {public_url}\n")
            break
    if public_url is None:
        print("❌ localtunnel 주소를 얻지 못했습니다. 별도 셀에서 !npx localtunnel --port 5001 --subdomain MindRoad 실행 필요")
    else:
        print(f"🔗 외부에서 {public_url}/mindmap 로 POST 요청을 보내면 Colab Flask로 연결됩니다.")

    app.run(port=5001, threaded=True)