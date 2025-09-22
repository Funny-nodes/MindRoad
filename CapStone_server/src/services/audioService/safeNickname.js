const slugify = require("slugify")
const INITIAL = [
  "g", "kk", "n", "d", "tt", "r", "m", "b", "pp",
  "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"
];
const MEDIAL = [
  "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o",
  "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"
];
const FINAL = [
  "", "k", "kk", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lp",
  "ls", "lt", "lp", "lh", "m", "p", "ps", "s", "ss", "ng", "c", "ch", "k", "t", "p", "h"
];

function isHangul(char) {
  const code = char.charCodeAt(0);
  return code >= 0xac00 && code <= 0xd7a3;
}

function romanizeKorean(str) {
  return str
    .split("")
    .map((char) => {
      if (!isHangul(char)) return char;

      const code = char.charCodeAt(0) - 0xac00;

      const cho = Math.floor(code / (21 * 28));
      const jung = Math.floor((code % (21 * 28)) / 28);
      const jong = code % 28;

      return INITIAL[cho] + MEDIAL[jung] + FINAL[jong];
    })
    .join("");
}

function makeSafeNickname(nickname) {
  const userName = nickname

  const onlyKorean = userName.replace(/[^가-힣]/g, "")
  const romanized = romanizeKorean(onlyKorean)
  const combined = userName.replace(onlyKorean,romanized)

  const safeNickname = slugify(combined, {
    replacement: "_",
    remove: /[^a-zA-Z0-9 _-]/g,
    lower: true,
    strict: true,
  })

  return safeNickname
}

function timeToSeconds(timeStr) {
  // "00:00:06" -> 6
  const [hh, mm, ss] = timeStr.split(":").map(Number);
  return hh * 3600 + mm * 60 + ss;
}

async function convertSegmentsToSRTJson(userSpeech) {
  const srtJson = [];

  for (const [nickname, segments] of Object.entries(userSpeech)) {
    // segments가 배열이 맞는지 확인
    if (!Array.isArray(segments)) continue;

    segments.forEach((seg) => {
      if (typeof seg !== "string") return; // 문자열만 처리

      const match = seg.match(/^\[(.*?)\]\s*(.*)$/);
      if (match) {
        const time = match[1];
        const speech = match[2];
        srtJson.push({ time, speaker: nickname, speech });
      }
    });
  }

  srtJson.sort((a, b) => {
    const [aStart, aEnd] = a.time.split(" --> ").map(timeToSeconds);
    const [bStart, bEnd] = b.time.split(" --> ").map(timeToSeconds);

    if (aStart !== bStart) return aStart - bStart; // 시작 시간이 빠른 순
    return aEnd - bEnd; // 시작이 같으면 끝나는 시간이 빠른 순
  });

  return srtJson;
}


// 두 문자열 간 Levenshtein Distance 계산
function levenshtein(a, b) {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) dp[i][j] = dp[i - 1][j - 1];
      else dp[i][j] = 1 + Math.min(dp[i - 1][j - 1], dp[i][j - 1], dp[i - 1][j]);
    }
  }
  return dp[m][n];
}

// 유사도 점수 계산 (1 - 거리/최대길이)
function similarity(a, b) {
  const dist = levenshtein(a, b);
  return 1 - dist / Math.max(a.length, b.length);
}

// 병합 STT에 스피커 매칭
async function replaceSpeaker(mergedSTT, userSTT) {
  return mergedSTT.map((mergedSeg) => {
    let bestSpeaker = mergedSeg.speaker || "unknown";
    let bestScore = -1;

    userSTT.forEach((uSeg) => {
      const score = similarity(mergedSeg.speech, uSeg.speech);
      if (score > bestScore) {
        bestScore = score;
        bestSpeaker = uSeg.speaker;
      }
    });

    return {
      ...mergedSeg,
      speaker: bestSpeaker
    };
  });
}


module.exports = { makeSafeNickname, convertSegmentsToSRTJson, replaceSpeaker }