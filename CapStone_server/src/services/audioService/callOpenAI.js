// callopenai.js
// 환경변수 미사용: 고정 BASE URL + /convsum 로 호출
// 사용 전: npm i axios

const axios = require("axios");

// 🔒 고정 공개 URL (터널 URL이 바뀌면 이 상수만 수정하세요)
const ADAPTER_BASE_URL = "https://mind-road4.loca.lt";

// 네트워크 옵션
const TIMEOUT_MS = 120_000; // 120초
const RETRIES = 2;          // 5xx/타임아웃 시 재시도 횟수

// 재시도 포함 POST 호출
async function postWithRetry(path, payload) {
  let lastErr;
  for (let attempt = 0; attempt <= RETRIES; attempt++) {
    try {
      const { data, status } = await axios.post(
        `${ADAPTER_BASE_URL}${path}`,
        payload,
        {
          headers: { "Content-Type": "application/json" },
          timeout: TIMEOUT_MS,
          validateStatus: () => true, // 비정상 상태코드도 잡아 로깅
        }
      );

      if (status >= 200 && status < 300 && data && typeof data === "object") {
        return data;
      }

      // 5xx, 429는 재시도 대상
      if ((status >= 500 && status < 600) || status === 429) {
        throw new Error(`HTTP ${status}: ${JSON.stringify(data)?.slice(0, 200)}`);
      }

      // 그 외(4xx 등)는 즉시 실패
      throw new Error(`HTTP ${status}: ${JSON.stringify(data)?.slice(0, 200)}`);
    } catch (err) {
      lastErr = err;
      const code = err?.code;
      const retryable =
        code === "ECONNABORTED" || // 타임아웃
        code === "ETIMEDOUT" ||
        code === "ECONNRESET" ||
        /HTTP 5\d\d|HTTP 429/.test(err?.message || "");

      // 재시도 진행
      if (retryable && attempt < RETRIES) {
        const backoff = Math.min(3000, 500 * 2 ** attempt);
        await new Promise((r) => setTimeout(r, backoff));
        continue;
      }

      // 최종 실패
      throw err;
    }
  }
  throw lastErr;
}

/**
 * @param {Object.<string, string>} speakerSpeech - { 닉네임: SRT 텍스트 }
 * @param {string[]} speakerNames - 화자 목록
 * @param {Array<Object>} nodeData - 현재 노드 데이터
 * @param {boolean} isRealTime - 실시간 모드 여부
 * @returns {Promise<any>} 어댑터 응답 JSON
 */
async function askOpenAI(speakerSpeech, speakerNames, nodeData, isRealTime = false) {
  try {
    if (!speakerSpeech || !speakerNames) return;

    const payload = { speakerSpeech, speakerNames, nodeData, isRealTime };
    const jsonResponse = await postWithRetry("/convsum", payload);

    // --- 후처리(안전망) ---
    if (!isRealTime && jsonResponse?.minutes && Array.isArray(jsonResponse.minutes.keywords)) {
      jsonResponse.minutes.keywords = [...new Set(jsonResponse.minutes.keywords)];
    }

    if (isRealTime && Array.isArray(jsonResponse?.keywords)) {
      const unique = [];
      const seen = new Set();
      for (const kw of jsonResponse.keywords) {
        const nm = kw?.name;
        if (nm && !seen.has(nm)) {
          seen.add(nm);
          unique.push({ name: nm, parent_key: kw.parent_key });
        }
        if (unique.length >= 2) break;
      }
      jsonResponse.keywords = unique;
    }

    return jsonResponse;
  } catch (error) {
    // 터널 503 등 상세 로그
    const status = error?.response?.status;
    const body = error?.response?.data;
    console.error(
      "어댑터 호출 오류:",
      status ? `HTTP ${status}` : error?.code || error?.message,
      body ? `\n응답본문: ${JSON.stringify(body).slice(0, 500)}` : ""
    );
    return null;
  }
}

module.exports = { askOpenAI };
