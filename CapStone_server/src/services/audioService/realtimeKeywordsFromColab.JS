// realtimeKeywordsFromColab.js
const axios = require("axios");
const ts = () => new Date().toISOString();

const TIMEOUT_MS = 120_000;
const RETRIES = 2;

/* ======================== 내부 유틸 ======================== */
// SRT JSON([{time,speaker,speech}, ...]) → "화자: 내용" 라인들
function srtJsonToTranscript(srtJson) {
  if (!Array.isArray(srtJson)) return "";
  return srtJson
    .map((seg) => {
      const spk = (seg?.speaker ?? "").toString().trim();
      const txt = (seg?.speech ?? "").toString().trim();
      if (!txt) return "";
      return spk ? `${spk}: ${txt}` : txt;
    })
    .filter(Boolean)
    .join("\n");
}

// DB 노드 스냅샷을 Colab이 기대하는 필드로 정규화
function normalizeNodes(nodes) {
  return (Array.isArray(nodes) ? nodes : []).map((n) => ({
    id: n.id ?? n.node_id ?? n.key ?? n._id,
    parent_key:
      n.parent_key !== undefined
        ? n.parent_key
        : n.parent !== undefined
        ? n.parent
        : null,
    content: n.content ?? n.name ?? "",
    x: n.x ?? 0,
    y: n.y ?? 0,
    project_id: n.project_id ?? n.projectId ?? undefined,
  }));
}

// 루트 노드 id 선택: parent_key가 null/0/"null"인 첫 노드, 없으면 첫 노드
function pickRootId(nodes) {
  for (const n of nodes) {
    const pk = n.parent_key;
    if (pk === null || pk === 0 || pk === "null" || pk === undefined) {
      return n.id ?? null;
    }
  }
  return nodes[0]?.id ?? null;
}

// 루트 라벨(토픽 기본값)
function pickRootLabel(nodes) {
  for (const n of nodes) {
    const pk = n.parent_key;
    if (pk === null || pk === 0 || pk === "null" || pk === undefined) {
      return n.content ?? n.name ?? "";
    }
  }
  return nodes[0]?.content ?? nodes[0]?.name ?? "";
}

// 중복 제거(키 기준)
function uniqueBy(arr, keyFn) {
  const seen = new Set();
  const out = [];
  for (const it of arr || []) {
    const k = keyFn(it);
    if (k == null) continue;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(it);
  }
  return out;
}

// 재시도 POST (+ 로깅)
async function postWithRetry(url, payload) {
  let lastErr;
  for (let attempt = 0; attempt <= RETRIES; attempt++) {
    const t0 = Date.now();
    try {
      console.log(
        `[RT] ${ts()} POST ${url} attempt=${attempt + 1} payload={max_k:${
          payload?.max_k
        }, nodes:${payload?.existing_nodes?.length ?? 0}}`
      );
      const { data, status } = await axios.post(url, payload, {
        headers: { "Content-Type": "application/json" },
        timeout: TIMEOUT_MS,
        validateStatus: () => true,
      });
      const ms = Date.now() - t0;

      if (status >= 200 && status < 300 && data && typeof data === "object") {
        const kwLen = Array.isArray(data.keywords) ? data.keywords.length : 0;
        console.log(
          `[RT] ${ts()} ✓ ${url} status=${status} time=${ms}ms keywords=${kwLen} placements=${
            Array.isArray(data.placements) ? data.placements.length : 0
          }`
        );
        return data;
      }

      console.warn(
        `[RT] ${ts()} ! ${url} HTTP ${status} time=${ms}ms body=${JSON.stringify(
          data
        )?.slice(0, 200)}`
      );
      if (status === 429 || (status >= 500 && status < 600)) {
        throw new Error(`HTTP ${status}`);
      }
      throw new Error(`HTTP ${status}`);
    } catch (err) {
      lastErr = err;
      const retryable =
        err?.code === "ECONNABORTED" ||
        err?.code === "ETIMEDOUT" ||
        err?.code === "ECONNRESET" ||
        /HTTP 5\d\d|HTTP 429/.test(err?.message || "");
      console.error(
        `[RT] ${ts()} ✗ ${url} attempt=${attempt + 1} error=${
          err?.code || err?.message
        }`
      );

      if (retryable && attempt < RETRIES) {
        const backoff = Math.min(3000, 500 * 2 ** attempt);
        console.log(`[RT] ${ts()} retry in ${backoff}ms`);
        await new Promise((r) => setTimeout(r, backoff));
        continue;
      }
      throw err;
    }
  }
  throw lastErr;
}

/* ======================== 공개 함수 ======================== */
/**
 * 코랩 /mindmap/suggest로 SRT→키워드+부모 배치 요청 후,
 * DB 삽입에 바로 쓸 수 있는 형태([{name, parent_key}])로 정규화하여 반환.
 */
async function extractRealtimeKeywordsFromColab({
  srtJson,
  nodeData,
  baseURL = "https://mind-road2.loca.lt",
  category = "",
  topic,
  maxK = 2,
  debug = true,
  requirePlacementParent = false,
  rootId,
}) {
  const nodes = normalizeNodes(nodeData || []);
  const root_id = rootId ?? pickRootId(nodes);
  const root_label = topic ?? pickRootLabel(nodes);
  const transcript = srtJsonToTranscript(srtJson);

  const payload = {
    category,
    transcript,
    topic: root_label || "일반",
    existing_nodes: nodes,
    root_id,
    max_k: maxK,
    debug: !!debug,
  };

  const url = `${baseURL.replace(/\/+$/, "")}/mindmap/suggest`;
  console.log(
    `[RT] ${ts()} → Colab request url=${url} cat=${category} topic="${
      payload.topic
    }" nodes=${nodes.length} segs=${
      Array.isArray(srtJson) ? srtJson.length : 0
    } max_k=${maxK}`
  );

  const raw = await postWithRetry(url, payload);

  const placements = Array.isArray(raw?.placements) ? raw.placements : [];
  const placementByName = new Map(
    placements.map((p) => [String(p?.content || "").trim(), p])
  );
  const names = Array.isArray(raw?.keywords) ? raw.keywords : [];
  const rootFallback = root_id ?? null;

  const out = [];
  for (const nm of names) {
    const name = String(nm || "").trim();
    if (!name) continue;
    const place = placementByName.get(name);
    if (place && place.parent_key != null && place.parent_key !== "null") {
      out.push({ name, parent_key: place.parent_key });
    } else if (!requirePlacementParent) {
      out.push({ name, parent_key: rootFallback });
    }
  }

  const uniq = uniqueBy(out, (k) => k?.name?.toLowerCase().replace(/\s+/g, ""));
  console.log(
    `[RT] ${ts()} ← Colab parsed keywords=${
      uniq.length
    } (requireParent=${requirePlacementParent})`
  );

  return { raw, keywords: uniq };
}

module.exports = { extractRealtimeKeywordsFromColab };
