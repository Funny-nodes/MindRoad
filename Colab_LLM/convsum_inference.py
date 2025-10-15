# convsum_inference.py - 깔끔한 범용 회의록 AI
import os
import re
import json
import torch
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from flask import Flask, request, jsonify
from functools import wraps

from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# ====== 구성 ======
BASE_MODEL = "EleutherAI/polyglot-ko-1.3b"
ADAPTER_PATH = "/content/meeting-minutes/adapter_ko_convsum"
MAX_NEW_TOKENS = 900
TEMPERATURE = 0.5
TOP_P = 0.9

MAX_BYTES = int(os.getenv("CONVSUM_MAX_BYTES", 2 * 1024 * 1024))
API_TOKEN = os.getenv("CONVSUM_TOKEN")

# ====== 모델 로딩 ======
print("Loading base tokenizer and model...")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, padding_side="left")
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto" if torch.cuda.is_available() else None,
    trust_remote_code=True,
)
print("Base model loaded.")

print("Loading LoRA adapter...")
model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
model.eval()
print("LoRA adapter loaded.")

# === Kiwi 준비 ===
try:
    from kiwipiepy import Kiwi
    KIWI = Kiwi()
    KIWI_AVAILABLE = True
    print("Kiwi loaded.")
except Exception:
    KIWI = None
    KIWI_AVAILABLE = False
    print("Kiwi not available.")

# ====== 범용 후처리 (Kiwi 기반) ======
def extract_content_keywords(text: str) -> List[str]:
    """실제 내용 키워드만 추출 (형태소 분석 기반)"""
    if not KIWI_AVAILABLE:
        return []
    
    # 메타 발화 제거 패턴 
    meta_patterns = [
        r'안녕하세요[^.]*\.',
        r'오늘\s*회의[^.]*\.',
        r'수고하셨습니다[^.]*\.',
        r'좋은\s*의견[^.]*\.',
        r'어떨까요[^.]*\?',
        r'것\s*같습니다[^.]*\.',
    ]
    
    cleaned_text = text
    for pattern in meta_patterns:
        cleaned_text = re.sub(pattern, ' ', cleaned_text, flags=re.IGNORECASE)
    
    # 형태소 분석
    tokens = KIWI.tokenize(cleaned_text, normalize_coda=True)
    keywords = []
    current_compound = []
    
    for token in tokens:
        surface, tag = token.form, token.tag
        
        # 불용어 스킬 (최소한만)
        if surface in ['것', '수', '등', '및', '나', '의', '을', '를', '이', '가', '에', '서', '로', '과', '와']:
            if current_compound:
                compound = ''.join(current_compound)
                if len(compound) >= 3:
                    keywords.append(compound)
                current_compound = []
            continue
        
        # 실질 명사, 고유명사, 외국어만 수집
        if tag in ('NNG', 'NNP', 'SL', 'SH') and len(surface) >= 2:
            current_compound.append(surface)
        else:
            if current_compound:
                compound = ''.join(current_compound)
                if len(compound) >= 3:
                    keywords.append(compound)
                current_compound = []
    
    # 마지막 처리
    if current_compound:
        compound = ''.join(current_compound)
        if len(compound) >= 3:
            keywords.append(compound)
    
    # 중복 제거 및 빈도 정렬
    keyword_freq = {}
    for kw in keywords:
        keyword_freq[kw] = keyword_freq.get(kw, 0) + 1
    
    sorted_keywords = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, freq in sorted_keywords]

def enhance_with_kiwi(srt_items: List[Dict[str, str]]) -> Dict[str, Any]:
    """Kiwi로 추출된 키워드를 기반으로 회의록 요소 개선"""
    full_text = " ".join([item.get("speech", "") for item in srt_items])
    keywords = extract_content_keywords(full_text)
    
    if not keywords:
        return {}
    
    # 상위 키워드들로 각 요소 생성
    top_keywords = keywords[:10]
    
    # topics: 상위 3-4개 키워드
    topics = top_keywords[:3] if len(top_keywords) >= 3 else top_keywords
    
    # purpose: 첫 번째 키워드 기반
    main_keyword = keywords[0] if keywords else "주요안건"
    if '활용' in full_text or '방안' in full_text:
        purpose = f"{main_keyword} 활용방안 검토."
    elif '개발' in full_text or '계획' in full_text:  
        purpose = f"{main_keyword} 개발계획 논의."
    else:
        purpose = f"{main_keyword} 관련 사항 논의."
    
    # summary: 주요 키워드들 조합
    if len(keywords) >= 2:
        summary = f"{keywords[0]}과 {keywords[1]} 관련 사항을 검토하고 향후 계획을 논의했습니다."
    else:
        summary = f"{main_keyword} 관련 사항을 검토하고 계획을 수립했습니다."
    
    # next_steps: 키워드 기반 액션
    next_steps = []
    time_hint = "(다음 회의)"
    
    for kw in top_keywords[:2]:
        if '계획' in full_text or '수립' in full_text:
            next_steps.append(f"{kw} 세부계획 수립{time_hint}.")
        else:
            next_steps.append(f"{kw} 추진방안 검토{time_hint}.")
    
    if not next_steps:
        next_steps = [f"{main_keyword} 관련 후속조치{time_hint}."]
    
    return {
        "topics": topics,
        "purpose": purpose, 
        "summary": summary,
        "next_steps": next_steps
    }

# ====== 강력한 프롬프트 (메인) ======
def build_strong_prompt(
    speaker_names: List[str],
    srt_items: List[Dict[str, str]],
    node_data: Any,
) -> str:
    """진짜 범용적인 강화 프롬프트 - 원칙 중심, 하드코딩 없음"""
    srt_text = _format_srt_from_items(srt_items)

    schema = (
        "{\n"
        '  "speakerNames": [string],\n'
        '  "srt": [ { "time": string, "speaker": string, "speech": string } ],\n'
        '  "minutes": {\n'
        '    "purpose": string,\n'
        '    "topics": [string],\n'
        '    "next_steps": [string],\n'
        '    "summary": string\n'
        "  }\n"
        "}"
    )

    # 실제 대화에서 키워드 추출해서 예시로 활용
    full_text = " ".join([item.get("speech", "") for item in srt_items])
    sample_keywords = extract_content_keywords(full_text)[:8]  # 상위 8개만
    
    universal_principles = (
        "핵심 원칙:\n\n"
        
        "1. 회의 메타 발화는 완전히 무시하십시오:\n"
        "   - 무시할 것: 인사말, 진행 멘트, 평가성 발언\n"
        "   - 예: '안녕하세요', '오늘 회의는', '어떨까요', '좋은 생각', '수고하셨습니다'\n\n"
        
        "2. 추상적 단어 대신 구체적 단어를 사용하십시오:\n"
        "   - 피할 것: '사용자', '서비스', '시스템', '방법', '방안', '기능'\n"
        "   - 사용할 것: 실제 언급된 제품명, 기술명, 활동명, 장소명\n\n"
        
        "3. 복합어로 의미를 만드십시오:\n"
        "   - 한 단어가 아닌 2-4단어 조합으로 구체적 개념 표현\n"
        "   - 실제 대화에서 연관되어 언급된 단어들을 조합\n\n"
        
        "4. 각 필드별 작성 원칙:\n\n"
        
        "   topics (3-4개):\n"
        "   - 대화에서 가장 많이 언급되거나 중요하게 다뤄진 구체적 주제\n"
        "   - 단순한 일반명사가 아닌 의미있는 개념이나 활동\n"
        "   - 이 회의가 다른 회의와 구별되는 고유한 내용\n\n"
        
        "   purpose:\n"
        "   - '무엇을' '어떻게 할 것인지' 구체적으로 명시\n"
        "   - '검토', '논의' 같은 추상적 동사보다는 구체적 목표\n\n"
        
        "   summary:\n"
        "   - 실제로 결정되거나 합의된 구체적 내용\n"
        "   - '검토했습니다'보다는 '무엇을 어떻게 하기로 했는지'\n\n"
        
        "   next_steps:\n"
        "   - 막연한 '검토'가 아닌 구체적 작업이나 산출물\n"
        "   - 누가 무엇을 언제까지 할지가 명확한 항목\n\n"
    )
    
    # 동적 예시 생성 (실제 대화 내용 기반)
    dynamic_examples = ""
    if sample_keywords:
        dynamic_examples = (
            f"이 대화에서 중요해 보이는 키워드들: {', '.join(sample_keywords)}\n"
            "이런 구체적 키워드들을 조합해서 의미있는 주제를 만드십시오.\n\n"
        )
    
    quality_check = (
        "품질 체크 (응답 전 자가 검증):\n"
        "□ topics에 '사용자', '서비스', '방법' 같은 추상어가 없는가?\n"
        "□ 이 회의의 고유한 특성이 드러나는가?\n"
        "□ 다른 회의록과 구별되는 구체적 내용인가?\n"
        "□ 실제 대화에서 언급된 내용을 기반으로 했는가?\n"
        "□ 문법과 띄어쓰기가 정확한가?\n\n"
    )

    prompt = (
        "전문 회의록 분석 시스템입니다.\n"
        "대화를 분석하여 핵심 내용을 추출하고 JSON으로 출력하십시오.\n\n"
        + universal_principles + "\n\n"
        + dynamic_examples
        + quality_check
        + "JSON SCHEMA:\n" + schema + "\n\n"
        + f"분석할 대화:\n{srt_text}\n\n"
        + "위 원칙을 엄격히 적용하여 JSON만 출력하십시오."
    )
    
    return prompt.strip()

# ====== 기존 유틸리티 함수들 ======
def _safe_json_extract(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        try:
            return json.loads(text)
        except Exception:
            return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    segment = text[start:i+1]
                    try:
                        return json.loads(segment)
                    except Exception:
                        break
    try:
        return json.loads(text)
    except Exception:
        return None

_TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,3}))?\s*$",
    re.MULTILINE
)

def _time_key_strict(t: str) -> Tuple[int, int, int, int]:
    m = _TIME_RE.match((t or "").strip())
    if not m:
        return (99, 99, 99, 999)
    hh, mm, ss, ms = m.groups()[0], m.groups()[1], m.groups()[2], m.groups()[3]
    return (int(hh), int(mm), int(ss), int(ms or 0))

def _format_srt_from_items(srt_items: List[Dict[str, str]]) -> str:
    lines = [f"{it['time']}\n{it['speaker']}: {it['speech']}" for it in srt_items]
    return "\n\n".join(lines)

def _normalize_speaker_srt_map(raw) -> Dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): ("" if v is None else str(v)) for k, v in raw.items()}
    if isinstance(raw, str):
        return {"S1": raw}

    if isinstance(raw, list):
        out_map: Dict[str, List[str]] = {}
        idx = 1
        for elem in raw:
            if isinstance(elem, dict) and {"time", "speaker", "speech"} <= set(elem.keys()):
                spk = str(elem.get("speaker") or f"S{idx}")
                seg = str(elem.get("speech") or "").strip()
                if seg:
                    out_map.setdefault(spk, []).append(seg)
                continue
            if isinstance(elem, dict):
                spk = str(elem.get("speaker") or elem.get("name") or f"S{idx}")
                srt = str(elem.get("srt") or elem.get("text") or elem.get("speech") or "").strip()
                if srt:
                    out_map.setdefault(spk, []).append(srt)
                    idx += 1
                continue
            if isinstance(elem, (tuple, list)) and len(elem) >= 2:
                spk = str(elem[0] or f"S{idx}")
                srt = str(elem[1] or "").strip()
                if srt:
                    out_map.setdefault(spk, []).append(srt)
                    idx += 1
                continue
            if isinstance(elem, str):
                out_map.setdefault(f"S{idx}", []).append(elem.strip())
                idx += 1
        return {spk: ". ".join(chunks) for spk, chunks in out_map.items()}
    return {}

def _parse_srt_map_to_items(speaker_srt_map: Dict[str, str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for nickname, srt_text in (speaker_srt_map or {}).items():
        if not srt_text:
            continue
        text = srt_text.replace("\r\n", "\n").replace("\r", "\n")
        matches = list(_TIME_RE.finditer(text))
        if not matches:
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            sec = 0
            for ln in lines:
                start = f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d},000"
                sec += 2
                end   = f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d},000"
                items.append({"time": f"{start} --> {end}", "speaker": nickname, "speech": ln})
            continue

        for idx, m in enumerate(matches):
            start_span = m.span()
            time_line = text[start_span[0]:start_span[1]].strip()
            content_start = start_span[1]
            content_end = matches[idx + 1].span()[0] if idx + 1 < len(matches) else len(text)
            content = text[content_start:content_end].strip()
            content = "\n".join([ln for ln in content.split("\n") if ln.strip() and not ln.strip().isdigit()]).strip()
            if not content:
                continue
            speech = re.sub(r"\s{2,}", " ", content.replace("\n", " ").strip())
            items.append({"time": time_line, "speaker": nickname, "speech": speech})
    items.sort(key=lambda it: _time_key_strict(it.get("time", "")))
    return items

def build_prompt_realtime_kr(srt_items: List[Dict[str, str]], node_data: Any) -> str:
    srt_text = _format_srt_from_items(srt_items)
    schema = "{\n  \"summary\": string\n}"
    prompt = (
        "실시간 회의 요약을 JSON으로 생성하십시오.\n\n"
        f"SCHEMA:\n{schema}\n\n"
        f"대화:\n{srt_text}\n"
    )
    return prompt.strip()

# ====== 생성 ======
def _generate(prompt: str) -> str:
    enc = tokenizer(prompt, return_tensors="pt")
    enc = {k: v.to(model.device) for k, v in enc.items() if k in ("input_ids", "attention_mask")}
    with torch.no_grad():
        output_ids = model.generate(
            **enc,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            do_sample=True,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    gen_ids = output_ids[0][enc["input_ids"].shape[1]:]
    text = tokenizer.decode(gen_ids, skip_special_tokens=True)
    return text

# ====== Flask ======
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES

def require_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if API_TOKEN:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {API_TOKEN}":
                return jsonify({"error": "UNAUTHORIZED"}), 401
        return f(*args, **kwargs)
    return wrapper

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "device": "cuda" if torch.cuda.is_available() else "cpu"})

@app.route("/convsum", methods=["POST"])
@require_token
def convsum():
    try:
        data = request.json or {}
        is_realtime = bool(data.get("isRealTime", False))
        raw_speaker = data.get("speakerSpeech")

        # 1) 입력 정규화/파싱
        srt_items: List[Dict[str, str]] = []
        speaker_names: List[str] = []
        srt_raw_map: Dict[str, str] = {}
        srt_raw_text: str = ""

        if isinstance(raw_speaker, list) and raw_speaker and all(
            isinstance(x, dict) and "time" in x and "speaker" in x and "speech" in x
            for x in raw_speaker
        ):
            srt_items = sorted(raw_speaker, key=lambda x: _time_key_strict(x.get("time", "")))
            speaker_names = data.get("speakerNames") or list(
                dict.fromkeys(it["speaker"] for it in srt_items if it.get("speaker"))
            )
            tmp_map: Dict[str, List[str]] = {}
            for it in srt_items:
                spk = (it.get("speaker") or "").strip() or "S"
                seg = (it.get("speech") or "").strip()
                if not seg:
                    continue
                tmp_map.setdefault(spk, []).append(seg)
            srt_raw_map = {k: ". ".join(v) for k, v in tmp_map.items()}
            srt_raw_text = "\n\n".join([f"### {spk}\n{txt}" for spk, txt in srt_raw_map.items()])
        else:
            speaker_srt_map = _normalize_speaker_srt_map(raw_speaker)
            srt_items = _parse_srt_map_to_items(speaker_srt_map)
            speaker_names = data.get("speakerNames") or list(speaker_srt_map.keys())
            srt_raw_map = {k: (v or "").strip() for k, v in speaker_srt_map.items()}
            srt_raw_text = "\n\n".join([f"### {spk}\n{txt}" for spk, txt in srt_raw_map.items()])

            if not srt_items:
                pseudo: List[Dict[str, str]] = []
                sec = 0
                for nickname, srt_text in (speaker_srt_map or {}).items():
                    txt = (srt_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
                    if not txt:
                        continue
                    sentences = [s.strip() for s in re.split(r"[.!?…]|[。]|[\.]{2,}|\n+", txt) if s.strip()]
                    for s in sentences:
                        start = f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d},000"
                        sec += 2
                        end   = f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d},000"
                        pseudo.append({"time": f"{start} --> {end}", "speaker": nickname, "speech": s})
                srt_items = pseudo

        if not srt_items:
            return jsonify({"error": "BAD_REQUEST", "detail": "No valid SRT items parsed from speakerSpeech."}), 400

        node_data = data.get("nodeData") or []

        # 2) LLM 생성 (강력한 프롬프트 사용)
        prompt = data.get("prompt")
        if not prompt:
            prompt = build_prompt_realtime_kr(srt_items, node_data) if is_realtime \
                     else build_strong_prompt(speaker_names, srt_items, node_data)

        gen = _generate(prompt)
        parsed = _safe_json_extract(gen) or {}

        # 3) 기본 구조 보장
        parsed["speakerNames"] = speaker_names
        parsed["srt"] = srt_items

        minutes = parsed.get("minutes", {}) if not is_realtime else parsed
        if minutes is None:
            minutes = {}

        # 4) Kiwi 기반 후처리로 개선 (LLM 결과가 빈약한 경우만)
        if KIWI_AVAILABLE:
            kiwi_result = enhance_with_kiwi(srt_items)
            
            # LLM 결과 검증 및 개선
            if not isinstance(minutes.get("topics"), list) or len(minutes.get("topics", [])) == 0:
                minutes["topics"] = kiwi_result.get("topics", ["주요안건"])
            
            if not minutes.get("purpose"):
                minutes["purpose"] = kiwi_result.get("purpose", "주요안건 논의.")
            
            if not minutes.get("summary"):
                minutes["summary"] = kiwi_result.get("summary", "주요 사항을 논의했습니다.")
                
            if not isinstance(minutes.get("next_steps"), list) or len(minutes.get("next_steps", [])) == 0:
                minutes["next_steps"] = kiwi_result.get("next_steps", ["주요 논의사항 정리(다음 회의)."])

        # 5) 최종 보정
        minutes.setdefault("topics", ["주요안건"])
        minutes.setdefault("purpose", "주요안건 논의.")
        minutes.setdefault("summary", "주요 사항을 논의했습니다.")
        minutes.setdefault("next_steps", ["주요 논의사항 정리(다음 회의)."])

        parsed["minutes"] = minutes
        parsed["srt_raw_map"] = srt_raw_map
        parsed["srt_raw_text"] = srt_raw_text

        return jsonify(parsed), 200

    except Exception as e:
        import traceback
        return jsonify({
            "error": "INTERNAL_ERROR",
            "detail": str(e),
            "trace": traceback.format_exc()[:2000],
        }), 500

if __name__ == "__main__":
    try:
        print("Launching localtunnel (fixed subdomain: mind-road4)...")
        tunnel = subprocess.Popen(
            ["npx", "localtunnel", "--port", "5000", "--subdomain", "mind-road4"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        PUBLIC_URL = "https://mind-road4.loca.lt"
        print(f"Public URL (fixed): {PUBLIC_URL}")
        print(f"POST {PUBLIC_URL}/convsum 로 요청하십시오.")
    except Exception as e:
        print(f"localtunnel 실행 오류: {e}")
        print("수동 실행 예: npx localtunnel --port 5000 --subdomain mind-road4")

    app.run(host="0.0.0.0", port=5000, threaded=True)