# =========================================
# Minimal server for /mindmap/suggest + localtunnel
# — Pinecone 벡터 보너스 기반 (하드 코딩 보너스 완전 제거)
# — 글로벌 예외 핸들러 + /healthz + 입력 검증/방어 추가
# — "루트/주제/카테고리 적합도" 동적 임계값(τ) + SBERT×Pinecone 혼합 점수
# — 카테고리별 (베이스 모델 + LoRA) 캐시 선로딩/늦은-로딩 지원
# =========================================
import warnings, time, torch, re, subprocess, os
from copy import deepcopy
from flask import Flask, request, jsonify
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from sentence_transformers import SentenceTransformer, util
from kiwipiepy import Kiwi
from difflib import SequenceMatcher
import torch.nn.functional as F
from collections import defaultdict, Counter
import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------- Optional: Pinecone import guard ----------
try:
    from pinecone import Pinecone
    _HAS_PINECONE = True
except Exception:
    _HAS_PINECONE = False

# ========== Pretty Logging Utils ==========
def hr(char="─", width=70):
    return char * width

def sec(title: str, icon="🟦", width=70):
    line = f"{icon} {title}"
    pad = max(0, width - len(line))
    return f"\n{line} {' ' * pad}\n{hr('─', width)}"

def kv(key, val, indent=2):
    return f"{' ' * indent}• {key}: {val}"

def list_bullets(items, indent=2, max_items=8):
    items = items[:max_items]
    return "\n".join([f"{' ' * indent}- {it}" for it in items]) if items else f"{' ' * indent}- (none)"

def table(rows, headers=None, indent=2, col_pad=2, max_rows=5):
    rows = rows[:max_rows]
    if headers:
        rows = [headers] + rows
    srows = [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in srows) for i in range(len(srows[0]))] if srows else []
    def fmt_row(r):
        cells = []
        for i, c in enumerate(r):
            pad = " " * (widths[i] - len(c) + col_pad)
            cells.append(c + pad)
        return " " * indent + "".join(cells).rstrip()
    out = []
    for ri, r in enumerate(srows):
        out.append(fmt_row(r))
        if headers and ri == 0:
            out.append(" " * indent + hr("─", sum(widths) + col_pad * len(widths)))
    return "\n".join(out) if out else " " * indent + "(empty)"

# ===========================================
# ---------- Config ----------
DOMAIN_CONFIG = {
    "관광및지역자원": {
        "lora_adapter_path": "./tour_data_all_adapter",
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "tour-index",
        # 벡터 보너스 스케일링 파라미터 (부모 추천 보너스 전용)
        "bonus_max": 0.15,
        "bonus_smin": 0.62,
        "bonus_smax": 0.85,
    },
    "의학및의료정보": {
        "lora_adapter_path": "./medical_data_adapter",
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "medical-index",
        "bonus_max": float(os.getenv("BONUS_MAX_MED", "0.12")),
        "bonus_smin": float(os.getenv("BONUS_SMIN_MED", "0.62")),
        "bonus_smax": float(os.getenv("BONUS_SMAX_MED", "0.85")),
    },
    "법률및행정": {
        "lora_adapter_path": "./legal_data_adapter",
        "pinecone_api_key": "pcsk_*****", # 마스킹 처리!
        "pinecone_index_name": "legal-index",
        "bonus_max": float(os.getenv("BONUS_MAX_LEGAL", "0.12")),
        "bonus_smin": float(os.getenv("BONUS_SMIN_LEGAL", "0.62")),
        "bonus_smax": float(os.getenv("BONUS_SMAX_LEGAL", "0.85")),
    },
}

TRANSCRIPT_PROMPT_TPL = {
    "관광및지역자원": (
        "다음 회의/발화 텍스트를 분석하여 '{topic}' 주제와 직접적으로 관련된 핵심 키워드를 5개 이내로 도출하라.\n"
        "- 각 키워드는 1~3개의 소단어 ... 각 소단어는 2~6자로 권장한다."
        "- 숫자/기호/조사/어미는 제거한다. 중복/유사 표현은 하나로 통합한다.\n"
        "- 결과는 쉼표로만 구분된 키워드 나열.\n"
        "- 반드시 텍스트에 실제로 등장한 어절/구만 사용하라.\n\n"
        "텍스트:\n{transcript}\n\n키워드:"
    ),
    "의학및의료정보": (
        "다음 의학 관련 텍스트에서 '{topic}'과 의미적으로 직접 연결되는 핵심 키워드를 5개 이내로 도출하라.\n"
        "- 2~3개 소단어(각 2~5자) 조합, 조사/어미/숫자 제거, 중복 통합.\n"
        "- 오직 쉼표로 구분된 키워드 목록만 출력.\n\n"
        "텍스트:\n{transcript}\n\n키워드:"
    ),
    "법률및행정": (
        "다음 법률/행정 텍스트에서 '{topic}' 관련 핵심 개념을 5개 이내로 도출하라.\n"
        "- 2~3개 소단어(각 2~5자), 조사/어미/숫자 제거, 유사 중복 제거.\n"
        "- 결과는 쉼표로만 구분된 키워드 나열.\n\n"
        "텍스트:\n{transcript}\n\n키워드:"
    ),
}

BASE_MODEL = "EleutherAI/polyglot-ko-1.3b"
MAX_FINAL_KEYWORDS = 5
POSITION_RADIUS_BASE = 160

STRICT_TRANSCRIPT_ONLY = True
SEMANTIC_FILL_THRESHOLD = 0.62

# ===== Debug switches =====
DEBUG_DEFAULT = True
TOPK_PARENTS_LOG = 5

# === parent policy ===
SIM_THRESHOLD_PARENT = float(os.getenv("SIM_THRESHOLD_PARENT", "0.48"))
PARENT_SIM_TAU       = float(os.getenv("PARENT_SIM_TAU", "0.60"))
DROP_WEAK_PARENT     = os.getenv("DROP_WEAK_PARENT", "false").lower() == "true"
RETURN_REJECTS       = os.getenv("RETURN_REJECTS", "true").lower() == "true"

# === Root relevance (동적 τ + 혼합 점수) ===
ROOT_RELEVANCE_MIX = float(os.getenv("ROOT_RELEVANCE_MIX", "0.50"))  # SBERT vs Pinecone
ROOT_TAU_FROM_PINECONE = os.getenv("ROOT_TAU_FROM_PINECONE", "true").lower() == "true"
ROOT_TAU_PERCENTILE = 0.50
ROOT_TAU_MIN = 0.45
ROOT_TAU_MAX = 0.70
ROOT_SIM_TAU_FALLBACK = float(os.getenv("ROOT_SIM_TAU_FALLBACK", "0.55"))
ANCHOR_WEIGHT = float(os.getenv("ANCHOR_WEIGHT", "0.25"))

# === Dynamic Anchor Settings ===
USE_DYNAMIC_ANCHORS = os.getenv("USE_DYNAMIC_ANCHORS", "true").lower() == "true"
ANCHOR_TOPK = int(os.getenv("ANCHOR_TOPK", "8"))                 # 최종 앵커 개수
ANCHOR_MATCHES_TOPK = int(os.getenv("ANCHOR_MATCHES_TOPK", "32"))# Pinecone 상위 매치 수
ANCHOR_FILTER_TYPE = os.getenv("ANCHOR_FILTER_TYPE", "keyword")   # Pinecone filter.type
ANCHOR_FREQ_WEIGHT = float(os.getenv("ANCHOR_FREQ_WEIGHT", "0.40"))
ANCHOR_SIM_WEIGHT  = float(os.getenv("ANCHOR_SIM_WEIGHT", "0.60"))
ANCHOR_MIN_TOKEN = 2   # 각 토큰 길이
ANCHOR_MAX_TOKEN = 5
ANCHOR_NGRAMS = (2, 3) # bi / tri-gram

SBERT_ONLY_TAU_MIN = 0.25
SBERT_ONLY_TAU_MAX = 0.55
SBERT_ONLY_TAU_OFFSET = -0.05

PRESENT_TAU_CAP_SBER_ONLY = float(os.getenv("PRESENT_TAU_CAP_SBER_ONLY", "0.33"))

# ---------- Runtime: tokenizer once ----------
print("🔵 Loading base tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, padding_side="left")
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
print("🟢 Tokenizer loaded.")

SBERT_MODEL = SentenceTransformer("snunlp/KR-SBERT-V40K-klueNLI-augSTS")
kiwi = Kiwi()

# ---------- NEW: category-wise (base + LoRA) cache ----------
_category_model_cache = {}  # {category: (tokenizer, lora_model)}

def _load_base_plus_lora_for(category: str):
    """카테고리 전용 베이스 모델을 새로 로드한 뒤 해당 LoRA를 얹어 반환"""
    cfg = DOMAIN_CONFIG.get(category)
    if cfg is None:
        return None, None
    print(f"🚀 [{category}] base 모델 + LoRA 로딩 시작...")
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True
    )
    lora = PeftModel.from_pretrained(base, cfg["lora_adapter_path"])
    lora.eval()
    print(f"✅ [{category}] 로딩 완료 (base+LoRA)")
    return tokenizer, lora

def build_category_model_cache(preload_all: bool = True):
    """
    서버 기동 시 3개 카테고리를 모두 올려둘지(preload_all=True),
    아니면 늦은-로딩(on-demand)만 쓸지 선택 가능.
    """
    if not preload_all:
        print("ℹ️ 카테고리 모델 캐시는 늦은-로딩 모드입니다.")
        return
    print("\n🚀 모든 카테고리별 base+LoRA 모델 캐시 생성 시작...\n")
    for category in DOMAIN_CONFIG.keys():
        if category in _category_model_cache:
            continue
        tok, lora = _load_base_plus_lora_for(category)
        if tok is not None and lora is not None:
            _category_model_cache[category] = (tok, lora)
            print(f"🧠 캐시됨: {category}")
    print("✅ 모든 카테고리 모델 캐시 완료!\n")

def get_model_and_tokenizer(category: str):
    """
    캐시에서 (tokenizer, lora_model) 반환.
    없으면 즉시 로드하여 캐시에 넣고 반환(늦은-로딩).
    """
    if category in _category_model_cache:
        return _category_model_cache[category]
    tok, lora = _load_base_plus_lora_for(category)
    if tok is not None and lora is not None:
        _category_model_cache[category] = (tok, lora)
    return tok, lora

# ---------- Common utils ----------
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())

def clean_transcript(text: str) -> str:
    if not text: return ""
    text = re.sub(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}"," ",text)
    text = re.sub(r"(?m)^\s*[\w가-힣]+:\s*","",text)
    text = re.sub(r"\s+"," ",text).strip()
    return text

# ---------- Keyword generation ----------
def batch_generate_keywords(batch_prompts, model, tok, debug=False):
    inputs = tok(batch_prompts, return_tensors="pt", padding=True, truncation=True, max_length=2048)
    if debug:
        print(sec("키워드 생성 요청", "🧩"))
        print(kv("배치 크기", len(batch_prompts)))
        print(kv("입력 토큰 길이≈", inputs['input_ids'].shape[1]))
    inputs = inputs.to(model.device)
    with torch.inference_mode():
        outputs = model.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            max_new_tokens=150,
            temperature=0.95, top_p=0.92, top_k=40,
            repetition_penalty=1.1, do_sample=True,
            pad_token_id=tok.eos_token_id, eos_token_id=tok.eos_token_id,
            use_cache=False,
        )
    results = []
    for i, out in enumerate(outputs):
        full = tok.decode(out, skip_special_tokens=True)
        tail = full[len(batch_prompts[i]):].strip()
        kws = [k.strip() for k in re.split(r"[,\n]", tail) if k.strip()]
        if debug:
            print(kv(f"배치#{i} 원시 후보(상위 10)", ", ".join(kws[:10])))
        results.append(kws)
    return results

def postprocess_keywords_with_kiwi(raw_keywords, reference_keywords=None, max_final_keywords=MAX_FINAL_KEYWORDS, debug=False):
    def extract_nouns(text):
        toks = kiwi.tokenize(text)
        return [t.form for t in toks if 'N' in t.tag and 2 <= len(t.form) <= 5]
    def is_similar(a,b,thr=0.65): return SequenceMatcher(None,a,b).ratio()>=thr

    cand_list, kw2cands = [], []
    for kw in raw_keywords:
        clean = re.sub(r"[^\w가-힣]"," ",kw).strip()
        nouns = extract_nouns(clean)
        if not nouns: kw2cands.append([]); continue
        joined = [" ".join(nouns)]
        joined = list(dict.fromkeys(joined))
        kw2cands.append(joined); cand_list.extend(joined)
    cand_list = list(dict.fromkeys(cand_list))

    cleaned, seen, seen_norm = [], [], set()
    for cands in kw2cands:
        for j in cands:
            norm = j.replace(" ","").lower()
            if norm in seen_norm: continue
            if any(is_similar(j, p) for p in seen): continue
            tokens = j.split()
            if not (1 <= len(tokens) <= 3): continue
            if any(len(t)<2 or len(t)>6 for t in tokens): continue
            seen.append(j); cleaned.append(j); seen_norm.add(norm)
            if len(cleaned) >= max_final_keywords: break
        if len(cleaned) >= max_final_keywords: break

    if not cleaned or not reference_keywords:
        if debug:
            print("[키워드 랭킹] 참조 구가 없어, 정제 결과만 사용:", cleaned)
        return [(kw, None, None) for kw in cleaned]

    key_embs = SBERT_MODEL.encode(cleaned, convert_to_tensor=True)
    ref_embs = SBERT_MODEL.encode(reference_keywords, convert_to_tensor=True)
    sims = util.pytorch_cos_sim(key_embs, ref_embs)

    if debug:
        print(f"[키워드 랭킹] 후보 {len(cleaned)}개, 참조 {len(reference_keywords)}개와 비교")

    scored = []
    for i, kw in enumerate(cleaned):
        row = sims[i]
        j = int(row.argmax().item())
        best = float(row[j].item())
        best_ref = reference_keywords[j]
        scored.append((kw, best, best_ref))
        if debug:
            print(f" - '{kw}' ↔ '{best_ref}'  최고유사도={best:.3f}")

    scored.sort(key=lambda x: (x[1] if x[1] is not None else -1), reverse=True)
    return scored[:max_final_keywords]

def filter_out_existing_keywords(keywords, existing_nodes):
    exist = {_norm(n.get("content","")) for n in (existing_nodes or [])}
    return [k for k in (keywords or []) if _norm(k) not in exist]

# ---------- Medical compound reinforcement ----------
def reinforce_domain_compounds(keyword: str, transcript: str) -> str:
    k_no = keyword.replace(" ", "")
    t_no = transcript.replace(" ", "")
    if ("혈당대처" in k_no) and ("저혈당" in t_no) and ("저혈당" not in k_no):
        return keyword.replace("혈당 대처", "저혈당 대처").replace("혈당대처","저혈당 대처")
    return keyword

# ---------- Root-context builders (SBERT/Pinecone 공통) ----------
def _root_context_vectors(category: str, topic: str, existing_nodes, root_id=None):
    ctx_texts = {}

    # (a) topic
    if topic and topic.strip():
        ctx_texts["topic"] = topic.strip()

    # (b) root label + first-depth children summary
    root_label = ""
    first_children = []
    rid = _find_root_id_db(existing_nodes or [], root_id)
    if rid:
        for n in (existing_nodes or []):
            if str(n.get("id")) == str(rid):
                root_label = (n.get("content") or "").strip()
            if str(n.get("parent_key")) == str(rid):
                lab = (n.get("content") or "").strip()
                if lab: first_children.append(lab)
    if root_label:
        ctx_texts["root"] = root_label
    if first_children:
        ctx_texts["root_children_summary"] = " ".join(first_children[:16])

    # (c) dynamic anchors (no hard-coding)
    anchors = _build_dynamic_category_anchors(category, topic or "", existing_nodes or [], root_id, debug=False)
    if anchors:
        ctx_texts["category_anchors"] = " ".join(anchors)

    ctx_vecs = {}
    for name, text in ctx_texts.items():
        v = SBERT_MODEL.encode(text, convert_to_tensor=True)
        v = F.normalize(v, p=2, dim=0)
        ctx_vecs[name] = v
    return ctx_vecs

def _root_context_text(category: str, topic: str, existing_nodes, root_id=None) -> str:
    parts = []
    if topic and topic.strip():
        parts.append(topic.strip())

    rid = _find_root_id_db(existing_nodes or [], root_id)
    root_label = ""
    first_children = []
    if rid:
        for n in (existing_nodes or []):
            if str(n.get("id")) == str(rid):
                root_label = (n.get("content") or "").strip()
            if str(n.get("parent_key")) == str(rid):
                lab = (n.get("content") or "").strip()
                if lab:
                    first_children.append(lab)
    if root_label:
        parts.append(root_label)
    if first_children:
        parts.append(" ".join(first_children[:16]))

    # dynamic anchors
    anchors = _build_dynamic_category_anchors(category, topic or "", existing_nodes or [], root_id, debug=False)
    if anchors:
        parts.append(" ".join(anchors))

    return " ".join([p for p in parts if p]).strip()

# ---------- Root relevance scoring (Pinecone side) ----------
_PINECONE_PC = {}
_PINECONE_INDEX = {}
_BONUS_CACHE = {}  # (category, parent_label, kw_text) -> float

def _get_pinecone_index(category: str):
    if not _HAS_PINECONE:
        return None
    cfg = DOMAIN_CONFIG.get(category) or {}
    api_key = cfg.get("pinecone_api_key")
    index_name = cfg.get("pinecone_index_name")
    if not (api_key and index_name):
        return None
    if category not in _PINECONE_PC:
        try:
            _PINECONE_PC[category] = Pinecone(api_key=api_key)
        except Exception:
            return None
    if category not in _PINECONE_INDEX:
        try:
            _PINECONE_INDEX[category] = _PINECONE_PC[category].Index(index_name)
        except Exception:
            return None
    return _PINECONE_INDEX[category]

def _pinecone_root_similarity_scores(category: str, keywords, ctx_text: str, top_k: int = 8, filter_type: str = "keyword"):
    out = {}
    index = _get_pinecone_index(category)
    if index is None or not keywords:
        return {kw: 0.0 for kw in (keywords or [])}
    try:
        for kw in keywords:
            query = f"{ctx_text} {kw}".strip()
            qvec = SBERT_MODEL.encode(query, convert_to_tensor=False).tolist()
            res = index.query(
                vector=qvec,
                top_k=top_k,
                include_metadata=True,
                filter={"type": filter_type}
            )
            matches = res.get("matches", []) or []
            s_max = max(float(m.get("score", 0.0)) for m in matches) if matches else 0.0
            out[kw] = max(0.0, min(1.0, s_max))
    except Exception:
        for kw in keywords:
            out.setdefault(kw, 0.0)
    return out

def _pinecone_dynamic_tau(category: str, ctx_text: str, top_k: int = 16, filter_type: str = "keyword") -> float:
    index = _get_pinecone_index(category)
    if index is None or not ctx_text.strip():
        return ROOT_SIM_TAU_FALLBACK
    try:
        qvec = SBERT_MODEL.encode(ctx_text, convert_to_tensor=False).tolist()
        res = index.query(
            vector=qvec,
            top_k=top_k,
            include_metadata=True,
            filter={"type": filter_type}
        )
        matches = res.get("matches", []) or []
        if not matches:
            return ROOT_SIM_TAU_FALLBACK
        scores = np.array([float(m.get("score", 0.0)) for m in matches], dtype=float)
        scores = np.clip(scores, 0.0, 1.0)
        tau = float(np.quantile(scores, ROOT_TAU_PERCENTILE))
        tau = max(ROOT_TAU_MIN, min(ROOT_TAU_MAX, tau))
        return tau
    except Exception:
        return ROOT_SIM_TAU_FALLBACK

# ----- Parent/position helpers -----
def _encode_labels(labels):
    e = SBERT_MODEL.encode(labels, convert_to_tensor=True)
    return F.normalize(e, p=2, dim=1)

def _find_root_id_db(existing_nodes, root_id):
    if root_id: return str(root_id)
    for n in existing_nodes:
        if n.get("parent_key") in (None, "", "null", 0):
            return str(n["id"])
    return str(existing_nodes[0]["id"]) if existing_nodes else None

def _quadrant(parent, child):
    dx = child["x"] - parent["x"]; dy = child["y"] - parent["y"]
    if dx >= 0 and dy < 0:  return "NE"
    if dx < 0  and dy < 0:  return "NW"
    if dx < 0  and dy >= 0: return "SW"
    return "SE"

def _choose_quadrant_for_new_child(parent, children):
    counts = {"NE":0,"NW":0,"SW":0,"SE":0}
    if (not children) or any(("x" not in c or "y" not in c) for c in children):
        return "NE"
    for c in children:
        try:
            if "x" in c and "y" in c:
                q = _quadrant(parent, c); counts[q]+=1
        except: pass
    return sorted(counts.items(), key=lambda kv: kv[1])[0][0]

def _position_offset(q, count_in_q):
    ring = count_in_q // 3 + 1
    r = POSITION_RADIUS_BASE * ring
    if q == "NE": return {"dx": +r, "dy": -r, "ring": ring}
    if q == "NW": return {"dx": -r, "dy": -r, "ring": ring}
    if q == "SW": return {"dx": -r, "dy": +r, "ring": ring}
    return {"dx": +r, "dy": +r, "ring": ring}

def _pinecone_vector_bonus(category: str, kw_text: str, parent_label: str,
                           top_k: int = 8, filter_type: str = "keyword") -> float:
    key = (category, parent_label, kw_text)
    if key in _BONUS_CACHE:
        return _BONUS_CACHE[key]
    try:
        index = _get_pinecone_index(category)
        if index is None:
            _BONUS_CACHE[key] = 0.0
            return 0.0
        query = f"{parent_label} {kw_text}".strip()
        qvec = SBERT_MODEL.encode(query, convert_to_tensor=False).tolist()
        res = index.query(
            vector=qvec,
            top_k=top_k,
            include_metadata=True,
            filter={"type": filter_type}
        )
        matches = res.get("matches", []) or []
        if not matches:
            _BONUS_CACHE[key] = 0.0
            return 0.0
        s_max = max(float(m.get("score", 0.0)) for m in matches)
        cfg = DOMAIN_CONFIG.get(category) or {}
        bonus_max = float(cfg.get("bonus_max", 0.12))
        smin = float(cfg.get("bonus_smin", 0.62))
        smax = float(cfg.get("bonus_smax", 0.85))
        s = max(0.0, min(s_max, 1.0))
        if s <= smin:
            bonus = 0.0
        elif s >= smax:
            bonus = bonus_max
        else:
            bonus = bonus_max * ((s - smin) / (smax - smin + 1e-8))
        _BONUS_CACHE[key] = float(bonus)
        return float(bonus)
    except Exception:
        _BONUS_CACHE[key] = 0.0
        return 0.0

def _bonus_score(category: str, kw_text: str, parent_label: str) -> float:
    return _pinecone_vector_bonus(category, kw_text, parent_label)

# ----- Parent/position recommendation -----
def _build_subtree_centroids(existing_nodes, node_ids, node_embs):
    id2idx = {nid: i for i, nid in enumerate(node_ids)}
    children_of = defaultdict(list)
    for n in existing_nodes:
        pk = n.get("parent_key")
        if pk in (None, "", "null", 0):
            continue
        p = str(pk); c = str(n["id"])
        if p in id2idx and c in id2idx:
            children_of[p].append(c)

    cents = []
    for nid in node_ids:
        idxs = [id2idx[nid]] + [id2idx[c] for c in children_of.get(nid, []) if c in id2idx]
        mat = node_embs[idxs]
        cent = F.normalize(mat.mean(dim=0, keepdim=True), p=2, dim=1).squeeze(0)
        cents.append(cent)
    return torch.stack(cents, dim=0)

def recommend_parents_and_positions_db(keywords, existing_nodes, root_id=None,
                                       debug=False, topk=TOPK_PARENTS_LOG, category="관광및지역자원"):
    if not existing_nodes:
        return [{"content": kw, "parent_key": None, "score": None, "position": {"strategy":"unpositioned"}} for kw in (keywords or [])]
    if not keywords:
        return []

    root = _find_root_id_db(existing_nodes, root_id)
    if root is None:
        return []

    node_ids    = [str(n["id"]) for n in existing_nodes]
    node_labels = [n.get("content","") or f"node_{i}" for i,n in enumerate(existing_nodes)]
    id_map      = {str(n["id"]): n for n in existing_nodes}
    label_map   = {str(n["id"]): (n.get("content","") or "") for n in existing_nodes}
    out         = []

    node_embs   = _encode_labels(node_labels)
    key_embs    = F.normalize(SBERT_MODEL.encode(keywords, convert_to_tensor=True), p=2, dim=1)

    existing_norms = {_norm(lab) for lab in node_labels}
    if key_embs.dim()!=2 or key_embs.size(1)==0:
        return []
    if node_embs.dim()!=2 or node_embs.size(1)==0:
        return [{"content": kw, "parent_key": int(root) if root.isdigit() else root, "score": None, "position":{"strategy":"slot-only","quadrant":"NE"}} for kw in keywords if _norm(kw) not in existing_norms]

    centroid_embs = _build_subtree_centroids(existing_nodes, node_ids, node_embs)

    alpha_by_cat = {"관광및지역자원": 0.70, "의학및의료정보": 0.68, "법률및행정": 0.62}
    alpha = alpha_by_cat.get(category, 0.67)

    base_sims = torch.matmul(key_embs, node_embs.T)

    for i, kw in enumerate(keywords):
        if _norm(kw) in existing_norms:
            continue

        key_vec  = key_embs[i]
        sub_sims = torch.matmul(key_vec, centroid_embs.T)
        combined = alpha * sub_sims + (1 - alpha) * base_sims[i]

        # ====== Pinecone-based bonus ONLY ======
        bonus = torch.tensor(
            [_bonus_score(category, kw, plab) for plab in node_labels],
            device=combined.device, dtype=combined.dtype
        )

        final_scores = combined + bonus

        # Root penalty
        root_penalty = 0.08
        def _is_root(nid):
            nd = id_map.get(str(nid))
            return (not nd) or (nd.get("parent_key") in (None, "", "null", 0))
        for j, nid in enumerate(node_ids):
            if _is_root(nid):
                final_scores[j] = final_scores[j] - root_penalty

        # Top-k
        k = min(topk, len(node_labels))
        vals, idxs = torch.topk(final_scores, k)
        max_idx = idxs[0]
        max_sc = float(vals[0].item())

        # If root is #1, try swap to a bonus-positive child if close
        if _is_root(node_ids[max_idx]) and k >= 2:
            for j in idxs[1:3]:
                plab = node_labels[j]
                if _bonus_score(category, kw, plab) > 0:
                    if (final_scores[max_idx] - final_scores[j]) <= 0.15:
                        max_idx = j
                        max_sc = float(final_scores[j].item())
                        break

        parent_candidate = node_ids[max_idx] if max_sc >= SIM_THRESHOLD_PARENT else None

        if debug:
            print(sec(f"부모 추천: '{kw}'", "🧭"))
            rows = []
            for rank, j in enumerate(idxs, start=1):
                plab = node_labels[j]
                s_sub = float(sub_sims[j].item())
                s_lab = float(base_sims[i, j].item())
                s_bon = _bonus_score(category, kw, plab)
                src = "vec" if s_bon > 0 else "-"
                s_fin = float((alpha * s_sub + (1 - alpha) * s_lab + s_bon))
                rows.append([rank, node_ids[j], plab, f"{s_sub:.3f}", f"{s_lab:.3f}", f"{s_bon:.3f} ({src})", f"{s_fin:.3f}"])
            print(table(rows, headers=["#","node_id","라벨","sub","lab","bonus","최종"], max_rows=TOPK_PARENTS_LOG))

            chosen_label = label_map.get(str(parent_candidate), "미지정")
            reason = (f"최종 {max_sc:.3f} ≥ 임계 {SIM_THRESHOLD_PARENT:.2f} → Top-1"
                      if parent_candidate else
                      f"최종 {max_sc:.3f} < 임계 {SIM_THRESHOLD_PARENT:.2f} → 부모 미지정")
            print(kv("부모 결정", f"id={parent_candidate} / 라벨='{chosen_label}'"))
            print(kv("사유", reason))

        parent_node = id_map.get(str(parent_candidate)) if parent_candidate else None
        children = [c for c in existing_nodes if str(c.get("parent_key")) == str(parent_candidate)] if parent_candidate else []

        # Positioning
        if not parent_node or ("x" not in parent_node or "y" not in parent_node):
            out.append({
                "content": kw,
                "parent_key": int(parent_candidate) if str(parent_candidate).isdigit() else parent_candidate,
                "score": round(max_sc, 4),
                "position": {"strategy":"slot-only","quadrant":"NE"}
            })
            continue

        q = _choose_quadrant_for_new_child(parent_node, children)
        cnt_q = sum(1 for c in children if "x" in c and "y" in c and _quadrant(parent_node, c) == q)
        pos = _position_offset(q, cnt_q)

        if debug and parent_node and ("x" in parent_node and "y" in parent_node):
            print(kv("좌표 배치", f"사분면={q}, 해당 사분면 기존 자식={cnt_q} → ring={pos['ring']}"))

        out.append({
            "content": kw,
            "parent_key": int(parent_candidate) if str(parent_candidate).isdigit() else parent_candidate,
            "score": round(max_sc, 4),
            "position": {"strategy":"quadrant","quadrant": q, **pos}
        })

    return out

def _noun_set(text: str):
    """텍스트에서 명사만 추출한 집합을 돌려준다."""
    try:
        return {t.form for t in kiwi.tokenize(text) if 'N' in t.tag}
    except Exception:
        return set()

def _phrase_in_nouns(phrase: str, noun_set: set[str]) -> bool:
    """
    '부동산 사기'처럼 2~3개 단어 키워드의 각 단어가
    실제 원문 명사 집합에 모두 존재하는지 검사.
    """
    tokens = [tok for tok in re.split(r"\s+", phrase.strip()) if tok]
    if not tokens:
        return False
    return all(tok in noun_set for tok in tokens)

def _extract_noun_ngrams(text: str, ngrams=(2,3), min_tok=2, max_tok=5, max_items=200):
    """텍스트에서 (2~3)-gram 명사구 후보를 뽑아 중복 제거 후 반환."""
    try:
        toks = [t.form for t in kiwi.tokenize(text) if 'N' in t.tag]
    except Exception:
        toks = []
    cands = []
    for n in ngrams:
        for i in range(len(toks)-n+1):
            chunk = toks[i:i+n]
            if all(min_tok <= len(w) <= max_tok for w in chunk):
                cands.append(" ".join(chunk))
    # 순서 보존 중복제거
    seen, out = set(), []
    for p in cands:
        k = re.sub(r"\s+","",p.lower())
        if k not in seen:
            seen.add(k); out.append(p)
    return out[:max_items]

def _flatten_meta_text(meta) -> str:
    """Pinecone metadata dict/list에서 텍스트성 값을 평탄화해 하나의 문자열로 합침."""
    parts = []
    def rec(x):
        if x is None:
            return
        if isinstance(x, dict):
            for v in x.values(): rec(v)
        elif isinstance(x, (list, tuple)):
            for v in x: rec(v)
        elif isinstance(x, (str, bytes)):
            try:
                s = x.decode("utf-8") if isinstance(x, bytes) else x
            except Exception:
                s = str(x)
            parts.append(s)
        else:
            parts.append(str(x))
    rec(meta)
    return " ".join(parts)

def _pinecone_anchor_terms(category: str, ctx_text: str, top_k_matches=ANCHOR_MATCHES_TOPK, debug=False):
    """
    ctx_text(= topic+root+children)로 Pinecone 질의 → 상위 매치들의 metadata에서
    명사 n-gram을 모아 빈도/유사도 기반으로 스코어링 후 상위 앵커 반환.
    """
    if not USE_DYNAMIC_ANCHORS:
        return []

    index = _get_pinecone_index(category)
    if index is None or not ctx_text.strip():
        return []

    try:
        qvec = SBERT_MODEL.encode(ctx_text, convert_to_tensor=False).tolist()
        res = index.query(
            vector=qvec,
            top_k=top_k_matches,
            include_metadata=True,
            filter={"type": ANCHOR_FILTER_TYPE} if ANCHOR_FILTER_TYPE else None
        )
        matches = res.get("matches", []) or []
        if not matches:
            return []

        # 1) 매치들의 메타 텍스트에서 n-gram 후보 수집 + 빈도
        all_text = []
        for m in matches:
            meta = m.get("metadata", {})
            txt = _flatten_meta_text(meta)
            if txt.strip():
                all_text.append(txt)
        if not all_text:
            return []

        joined = " ".join(all_text)
        candidates = _extract_noun_ngrams(joined, ngrams=ANCHOR_NGRAMS,
                                          min_tok=ANCHOR_MIN_TOKEN, max_tok=ANCHOR_MAX_TOKEN,
                                          max_items=800)
        if not candidates:
            return []

        freq = Counter(candidates)
        uniq = list(freq.keys())

        # 2) ctx_text와 코사인 유사도
        ctx_vec = SBERT_MODEL.encode(ctx_text, convert_to_tensor=True)
        ctx_vec = F.normalize(ctx_vec, p=2, dim=0)
        cand_vecs = SBERT_MODEL.encode(uniq, convert_to_tensor=True)
        cand_vecs = F.normalize(cand_vecs, p=2, dim=1)
        sims = torch.matmul(cand_vecs, ctx_vec).cpu().numpy()

        # 3) 스코어: w_sim * sim + w_freq * normalized_freq
        fvals = np.array([freq[u] for u in uniq], dtype=float)
        if fvals.max() > 0:
            fvals = fvals / fvals.max()
        score = ANCHOR_SIM_WEIGHT * sims + ANCHOR_FREQ_WEIGHT * fvals

        ranked = sorted(zip(uniq, score, sims, fvals), key=lambda x: x[1], reverse=True)

        # 4) 상위 ANCHOR_TOPK 개 유사/다양성 보장(근사)
        out, seen_norm = [], set()
        for term, sc, si, fr in ranked:
            k = re.sub(r"\s+","", term.lower())
            if k in seen_norm:
                continue
            out.append(term)
            seen_norm.add(k)
            if len(out) >= ANCHOR_TOPK:
                break

        if debug:
            print(sec("동적 앵커 후보 (Pinecone 기반)", "🧲"))
            rows = []
            for term, sc, si, fr in ranked[:min(ANCHOR_TOPK, 10)]:
                rows.append([term, f"{si:.3f}", f"{fr:.2f}", f"{sc:.3f}"])
            print(table(rows, headers=["term","sim","freq","score"], max_rows=10))

        return out

    except Exception as e:
        if debug:
            print("[동적 앵커] 예외:", e)
        return []

_ANCHOR_CACHE = {}

def _build_dynamic_category_anchors(category: str, topic: str, existing_nodes, root_id=None, debug=False):
    """
    topic + root + first-children로 만든 컨텍스트 텍스트를 쿼리로,
    Pinecone에서 앵커를 뽑고 없으면 로컬 n-gram으로 대체.
    """
    rid = _find_root_id_db(existing_nodes or [], root_id)
    root_label = ""
    first_children = []
    if rid:
        for n in (existing_nodes or []):
            if str(n.get("id")) == str(rid):
                root_label = (n.get("content") or "").strip()
            if str(n.get("parent_key")) == str(rid):
                lab = (n.get("content") or "").strip()
                if lab:
                    first_children.append(lab)

    parts = []
    if topic and topic.strip():
        parts.append(topic.strip())
    if root_label:
        parts.append(root_label)
    if first_children:
        parts.append(" ".join(first_children[:16]))
    ctx_text = " ".join([p for p in parts if p]).strip()

    # 캐시 키
    cache_key = (category, ctx_text)
    if cache_key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[cache_key]

    anchors = _pinecone_anchor_terms(category, ctx_text, top_k_matches=ANCHOR_MATCHES_TOPK, debug=debug)

    # Pinecone 결과가 없으면 로컬에서 n-gram 추출
    if not anchors and ctx_text:
        local_terms = _extract_noun_ngrams(ctx_text, ngrams=ANCHOR_NGRAMS,
                                           min_tok=ANCHOR_MIN_TOKEN, max_tok=ANCHOR_MAX_TOKEN,
                                           max_items=200)
        anchors = local_terms[:ANCHOR_TOPK]

    _ANCHOR_CACHE[cache_key] = anchors
    if debug:
        print(sec("최종 동적 앵커", "🏷️"))
        print(list_bullets(anchors, max_items=ANCHOR_TOPK))
    return anchors

# ---------- Keyword extractor with root-relevance dynamic τ ----------
def extract_keywords_from_transcript(transcript, category, topic=None,
                                     max_k=MAX_FINAL_KEYWORDS, debug=False,
                                     existing_nodes=None, root_id=None):
    if not (transcript and transcript.strip()):
        return []
    tok, lora_model = get_model_and_tokenizer(category)
    if tok is None or lora_model is None:
        return []

    def _n(s): return re.sub(r"\s+","", s.lower())

    def phrases_from_text(text, max_items=30):
        try:
            toks = [t.form for t in kiwi.tokenize(text) if 'N' in t.tag]
        except:
            toks = []
        phrases = []
        for n in (2,3):
            for i in range(len(toks)-n+1):
                chunk = toks[i:i+n]
                if all(2<=len(w)<=5 for w in chunk):
                    phrases.append(" ".join(chunk))
        seen, out = set(), []
        for p in phrases:
            k = _n(p)
            if k not in seen:
                seen.add(k); out.append(p)
        return out[:max_items]

    # === (A) 원문 명사 집합 ===
    noun_set = _noun_set(transcript)

    ref_phrases = phrases_from_text(transcript)
    ref_for_rank = ref_phrases if ref_phrases else (topic.split() if topic else [])
    if debug:
        print(sec("참조 구(랭킹 기준)", "📌"))
        print(list_bullets(ref_for_rank, max_items=15))

    # LLM 생성
    prompt_tpl = TRANSCRIPT_PROMPT_TPL.get(category) or TRANSCRIPT_PROMPT_TPL["관광및지역자원"]
    prompt = prompt_tpl.format(topic=(topic or "일반"), transcript=transcript.strip())
    gen_list = batch_generate_keywords([prompt], lora_model, tok, debug=debug)
    raw_keywords = gen_list[0] if gen_list else []
    if debug:
        print(sec("정제 대상(생성 원시 후보 요약)", "🧹"))
        print(list_bullets(raw_keywords, max_items=10))

    # KIWI 정제 + 참조구 기반 1차 랭킹
    final_scored = postprocess_keywords_with_kiwi(
        raw_keywords,
        reference_keywords=ref_for_rank,
        max_final_keywords=max_k*3,
        debug=debug
    )

    # === (B) 원문 n-gram을 LLM 후보에 '초기에' 병합 (핵심 보강) ===
    ngrams = phrases_from_text(transcript, max_items=40)
    cand_all = []
    _seen = set()
    def _push_kw_triplet(kw, sim=None, ref=None):
        k = _n(kw)
        if k not in _seen:
            _seen.add(k)
            cand_all.append((kw, sim, ref))

    for kw, sim, ref in final_scored:
        _push_kw_triplet(kw, sim, ref)
    for kw in ngrams:
        _push_kw_triplet(kw, None, None)

    # === (C) 원문 등장 여부: '문자열 포함' -> '명사 집합 포함' ===
    present, absent = [], []
    for kw, best_sim, best_ref in cand_all:
        if _phrase_in_nouns(kw, noun_set):
            present.append((kw, best_sim, best_ref))
        else:
            absent.append((kw, best_sim, best_ref))

    selected = [kw for kw, _, _ in present[:max_k]]
    if debug and present:
        print(sec("채택된 키워드(원문 등장)", "✅"))
        rows = []
        for kw, s, ref in present[:max_k]:
            rows.append([kw, f"{s:.3f}" if s is not None else "—", ref])
        print(table(rows, headers=["키워드", "유사도", "근거구"], max_rows=max_k))

    # 부족 시(옵션) 의미 보완 (느슨 모드에서만 + 명사 검증 통과 조건)
    if len(selected) < max_k and not STRICT_TRANSCRIPT_ONLY:
        try:
            emb_t = SBERT_MODEL.encode(transcript, convert_to_tensor=True)
            if absent:
                abs_labels = [kw for kw, _, _ in absent]
                emb_c = SBERT_MODEL.encode(abs_labels, convert_to_tensor=True)
                sims = util.pytorch_cos_sim(emb_c, emb_t.unsqueeze(0)).squeeze(1)
                order = sims.argsort(descending=True).tolist()
                for idx in order:
                    simv = float(sims[idx].item())
                    if simv >= SEMANTIC_FILL_THRESHOLD and _phrase_in_nouns(abs_labels[idx], noun_set):
                        selected.append(abs_labels[idx])
                        if debug:
                            print(f"[보완 선택] 의미 유사도≥{SEMANTIC_FILL_THRESHOLD} & 명사검증통과: '{abs_labels[idx]}' (유사도={simv:.3f})")
                        if len(selected) >= max_k: break
        except Exception as e:
            if debug:
                print("[보완 선택] 임시 건너뜀(오류):", e)

    # 중복 제거
    selected = list(dict.fromkeys(selected))

    # ===== (D) 루트/주제 적합도: 동적 τ + SBERT×Pinecone 혼합 =====
    try:
        # 1) 컨텍스트 텍스트 및 동적 τ
        ctx_text = _root_context_text(category, topic or "", existing_nodes or [], root_id)
        if ROOT_TAU_FROM_PINECONE:
            tau = _pinecone_dynamic_tau(category, ctx_text, top_k=16, filter_type="keyword")
        else:
            tau = ROOT_SIM_TAU_FALLBACK

        # 2) SBERT 적합도
        ctx_vecs = _root_context_vectors(category, topic or "", existing_nodes or [], root_id)
        kw_vecs = SBERT_MODEL.encode(selected, convert_to_tensor=True) if selected else torch.empty(0)
        kw_vecs = F.normalize(kw_vecs, p=2, dim=1) if selected else kw_vecs

        keys_primary = [k for k in ["topic","root","root_children_summary"] if k in ctx_vecs]
        has_anchor  = ("category_anchors" in ctx_vecs)

        sbert_scores = []
        for i, kw in enumerate(selected):
            v = kw_vecs[i]
            vals = []
            for k in keys_primary:
                vals.append(float(torch.matmul(v, ctx_vecs[k]).item()))
            best_val = max(vals) if vals else -1.0
            if has_anchor and best_val >= 0:
                anchor_sim = float(torch.matmul(v, ctx_vecs["category_anchors"]).item())
                best_val = max(best_val, (1-ANCHOR_WEIGHT)*best_val + ANCHOR_WEIGHT*anchor_sim)
            sbert_scores.append(max(0.0, min(1.0, best_val)))

        # 3) Pinecone 적합도
        pc_scores_map = _pinecone_root_similarity_scores(category, selected, ctx_text, top_k=8, filter_type="keyword")
        pc_scores = [pc_scores_map.get(kw, 0.0) for kw in selected]

        # === Pinecone이 전부 0이면 SBERT-only로 강등 + τ 재산정 ===
        lam = ROOT_RELEVANCE_MIX
        pc_all_zero = (not pc_scores) or all(s <= 1e-6 for s in pc_scores)
        if pc_all_zero:
            lam = 0.0
            if sbert_scores:
                tau_sb = float(np.quantile(np.array(sbert_scores, dtype=float), ROOT_TAU_PERCENTILE))
                tau = tau_sb + SBERT_ONLY_TAU_OFFSET
                tau = max(SBERT_ONLY_TAU_MIN, min(SBERT_ONLY_TAU_MAX, tau))
            else:
                tau = SBERT_ONLY_TAU_MIN

        # 4) 혼합 + τ 필터
        mixed = [(selected[i], (1-lam)*sbert_scores[i] + lam*pc_scores[i], sbert_scores[i], pc_scores[i]) for i in range(len(selected))]

        # SBERT-only면 '원문 등장 키워드'에 한해 더 완화된 τ 사용
        if pc_all_zero:
            tau_present = min(tau, PRESENT_TAU_CAP_SBER_ONLY)
        else:
            tau_present = tau

        def _kw_passes(kw, score_mixed):
            is_present = _phrase_in_nouns(kw, noun_set)
            th = tau_present if is_present else tau
            return score_mixed >= th

        filtered = [(kw, m) for (kw, m, sbert, pc) in mixed if _kw_passes(kw, m)]
        if filtered:
            filtered.sort(key=lambda x: x[1], reverse=True)
            selected = [kw for (kw, _) in filtered[:max_k]]
        else:
            # 백업: transcript n-gram에서 루트 적합도 높은 것 재선정 (느슨한 모드에서만)
            if not STRICT_TRANSCRIPT_ONLY:
                try:
                    ngrams2 = _extract_noun_ngrams(transcript, ngrams=(2,3), max_items=40)
                    if ngrams2:
                        pc_map2 = _pinecone_root_similarity_scores(category, ngrams2, ctx_text, top_k=8, filter_type="keyword")
                        kwv2 = SBERT_MODEL.encode(ngrams2, convert_to_tensor=True)
                        kwv2 = F.normalize(kwv2, p=2, dim=1)
                        sbert2 = []
                        for i, kw in enumerate(ngrams2):
                            v = kwv2[i]
                            vals = []
                            for k in keys_primary:
                                vals.append(float(torch.matmul(v, ctx_vecs[k]).item()))
                            best_val = max(vals) if vals else -1.0
                            if "category_anchors" in ctx_vecs and best_val >= 0:
                                anchor_sim = float(torch.matmul(v, ctx_vecs["category_anchors"]).item())
                                best_val = max(best_val, (1-ANCHOR_WEIGHT)*best_val + ANCHOR_WEIGHT*anchor_sim)
                            sbert2.append(max(0.0, min(1.0, best_val)))
                        lam2 = lam  # pc_all_zero면 0.0
                        mixed2 = [(ngrams2[i], (1-lam2)*sbert2[i] + lam2*pc_map2.get(ngrams2[i], 0.0)) for i in range(len(ngrams2))]
                        mixed2.sort(key=lambda x: x[1], reverse=True)
                        selected = [kw for (kw, m) in mixed2 if m >= (tau+0.03) and _phrase_in_nouns(kw, noun_set)][:max_k]
                    else:
                        selected = []
                except Exception:
                    selected = []
            else:
                selected = []

            # 토픽 백업
            if not selected and (not STRICT_TRANSCRIPT_ONLY) and topic:
                toks = [w for w in re.split(r"[\s,/]+", topic) if 2<=len(w)<=10 and w in noun_set]
                selected = toks[:max_k]

    except Exception as e:
        if debug:
            print("[루트 적합도(동적 τ)] 예외로 인해 우회:", e)
        # 실패 시 기존 selected 유지

    # 도메인 특화 보정
    if category == "의학및의료정보":
        before = list(selected)
        selected = [reinforce_domain_compounds(k, transcript) for k in selected]
        if debug and before != selected:
            print(sec("도메인 보정(의료 합성)", "🧬"))
            print(kv("Before", ", ".join(before)))
            print(kv("After ", ", ".join(selected)))

    # === (E) 최종 이중 안전장치 ===
    if STRICT_TRANSCRIPT_ONLY and selected:
        selected = [kw for kw in selected if _phrase_in_nouns(kw, noun_set)]

    return selected[:max_k]

# ---------- Flask ----------
app = Flask(__name__)

# ---- 글로벌 예외 핸들러: 500 원인 가시화 ----
@app.errorhandler(Exception)
def handle_all_errors(e):
    import traceback, sys
    tb = "".join(traceback.format_exception(*sys.exc_info()))
    print(sec("UNCAUGHT EXCEPTION", "💥"))
    print(tb)
    return jsonify({"error": "internal_error", "detail": str(e)}), 500

# ---- 헬스체크 ----
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({
        "ok": True,
        "model_loaded": bool(_category_model_cache),
        "has_pinecone": _HAS_PINECONE
    }), 200

# ---- 메인 라우트 ----
@app.route("/mindmap/suggest", methods=["POST"])
def mindmap_suggest():
    try:
        data = request.json or {}
        debug = bool(data.get("debug", DEBUG_DEFAULT))

        # category 공백 제거
        category_raw = data.get("category")
        category = "".join(category_raw.split()) if isinstance(category_raw, str) else None

        transcript_raw = (data.get("transcript") or "").strip()
        existing_nodes = data.get("existing_nodes") or []
        topic = (data.get("topic") or "").strip()
        root_id = data.get("root_id")

        # ---- 입력 검증: 필수 항목 누락 시 400 ----
        missing = []
        if not category:      missing.append("category")
        if not transcript_raw: missing.append("transcript")
        if missing:
            return jsonify({
                "error": "bad_request",
                "missing": missing,
                "message": "required fields missing"
            }), 400

        transcript = clean_transcript(transcript_raw)
        try:
            max_k = int(data.get("max_k", MAX_FINAL_KEYWORDS))
        except Exception:
            max_k = MAX_FINAL_KEYWORDS

        if category not in DOMAIN_CONFIG:
            return jsonify({"error": f"지원하지 않는 주제입니다: {category}"}), 400

        # 1) 키워드 추출
        keywords = extract_keywords_from_transcript(
            transcript, category, topic,
            max_k=max_k, debug=debug,
            existing_nodes=existing_nodes, root_id=root_id
        )
        keywords = filter_out_existing_keywords(keywords, existing_nodes)

        # 2) 부모/좌표 추천
        placements = recommend_parents_and_positions_db(
            keywords, existing_nodes, root_id=root_id, debug=debug, topk=TOPK_PARENTS_LOG, category=category
        )

        # 3) 점수 낮은 배치 제거 (옵션)
        rejected = []
        if DROP_WEAK_PARENT:
            pruned = []
            placed_names = set()
            for p in placements:
                pk = p.get("parent_key")
                sc = p.get("score")
                if pk not in (None, "", "null") and (sc is None or sc >= PARENT_SIM_TAU):
                    pruned.append(p)
                    placed_names.add(p.get("content"))
                else:
                    rejected.append({"content": p.get("content"),
                                    "reason": f"parent={pk}, score={sc}, tau={PARENT_SIM_TAU}"})
            placements = pruned

        # 4) project_id 채워넣기
        project_id = next((n.get("project_id") for n in existing_nodes if n.get("project_id") is not None), None)
        for p in placements:
            p["project_id"] = project_id

        resp = {"keywords": keywords, "placements": placements}
        if RETURN_REJECTS:
            resp["rejected"] = rejected
        return jsonify(resp)

    except Exception as e:
        print(sec("ROUTE /mindmap/suggest ERROR", "💥"))
        import traceback, sys
        tb = "".join(traceback.format_exception(*sys.exc_info()))
        print(tb)
        return jsonify({"error":"internal_error", "detail": str(e)}), 500

# ---------- Localtunnel launcher ----------
def ensure_localtunnel(port=5002, preferred_subdomain="mind-road2",
                       alt_subdomains=("mind-road3","mind-road4"),
                       timeout=45):
    candidates = []
    if preferred_subdomain:
        candidates.append(preferred_subdomain)
    candidates.extend(list(alt_subdomains))
    candidates.append(None)  # 마지막은 랜덤

    for sub in candidates:
        args = ["npx", "localtunnel", "--port", str(port)]
        if sub:
            args += ["--subdomain", sub]
            print(f"🌐 localtunnel 시도: {' '.join(args)} (선호='{sub}')")
        else:
            print(f"🌐 localtunnel 시도: {' '.join(args)} (랜덤)")

        proc = subprocess.Popen(args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                bufsize=1)

        url, start = None, time.time()
        while time.time() - start < timeout:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            line = line.strip()
            low = line.lower()
            if "your url is:" in low:
                url = line.split("your url is:")[-1].strip()
                print(f"🔗 Public URL: {url}")
                return url, proc
            if any(k in low for k in ["error", "cannot", "failed", "not available", "bad request"]):
                break

        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    print("❌ localtunnel URL 획득 실패")
    return None, None

if __name__ == "__main__":
    from threading import Thread
    import atexit

    lt_proc = None
    def _cleanup_lt():
        global lt_proc
        try:
            if lt_proc and lt_proc.poll() is None:
                lt_proc.terminate()
                try: lt_proc.wait(timeout=3)
                except: lt_proc.kill()
        except Exception as e:
            print("localtunnel 정리 중 예외:", e)
    atexit.register(_cleanup_lt)

    def run_flask():
        app.run(host="0.0.0.0", port=5002, threaded=True, use_reloader=False)

    # 선제 포트 정리(콜랩 재실행 잔재 방지)
    try:
        import shlex
        p = subprocess.run(shlex.split("lsof -ti:5002"), capture_output=True, text=True)
        for pid in [x for x in p.stdout.strip().splitlines() if x]:
            subprocess.run(["kill", "-9", pid])
            print(f"Killed PID {pid} on :5002")
    except Exception:
        pass

    # ✅ 카테고리별 모델 선로딩 (GPU 메모리가 부족하면 False로 바꾸고 늦은-로딩만 사용)
    build_category_model_cache(preload_all=True)

    t = Thread(target=run_flask, daemon=True)
    t.start()

    # 모델/LoRA 워밍업 (임의 카테고리로 더미 generate)
    tok, lora = get_model_and_tokenizer("관광및지역자원")
    if tok is not None and lora is not None:
        _ = batch_generate_keywords(["키워드:"], lora, tok, debug=False)

    # mind-road2 선호, 불가 시 mind-road3/4 → 랜덤
    public_url, lt_proc = ensure_localtunnel(
        port=5002,
        preferred_subdomain="mind-road2",
        alt_subdomains=("mind-road3", "mind-road4"),
        timeout=45,
    )

    if public_url:
        print(f"\n✅ 외부에서 {public_url}/mindmap/suggest 로 POST 요청 가능합니다.")
        print(f"✅ 헬스체크: {public_url}/healthz")
    else:
        print("\n⚠️ localtunnel이 열리지 않았습니다. 수동 실행 예:")
        print("   !npx localtunnel --port 5002 --subdomain mind-road2")

    t.join()
