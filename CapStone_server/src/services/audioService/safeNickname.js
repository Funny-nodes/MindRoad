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

function convertSegmentsToSRTJson(userSpeech) {
  const srtJson = [];

  for (const [nickname, segments] of Object.entries(userSpeech)) {
      
    const segmentArray = Array.isArray(segments)
      ? segments
      : Object.values(segments);
  
    segmentArray.forEach((seg) => {
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

module.exports = { makeSafeNickname, convertSegmentsToSRTJson }