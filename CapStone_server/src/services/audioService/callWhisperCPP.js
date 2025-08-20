const fs = require("fs")
const path = require("path")
const { exec } = require("child_process");


async function callWhisperCPP(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error("❌ 파일이 존재하지 않습니다: " + filePath);
  }

  const modelName = "ggml-medium.bin"
  const projectRoot = path.resolve(__dirname, "../", "../", "../")

  const whisperBinary = path.resolve(
    projectRoot,
    "whisper.cpp",
    "build",
    "bin",
    "Release",
    "whisper-cli.exe"
  ); // Whisper 실행 파일 경로

  const modelPath = path.resolve(
    projectRoot,
    "whisper.cpp",
    "models",
    `${modelName}`
  ); // 모델 경로

  // os.cpus().length
  const threads = 16;
  const command = `"${whisperBinary}" -m "${modelPath}" -f "${filePath}" --language ko -t ${threads} -bs 1 -bo 1`;

  return new Promise((resolve, reject) => {
    exec(command, { maxBuffer: 1024 * 500 }, (error, stdout, stderr) => {
      if (error) {
        console.error("❌ Whisper 실행 실패:", error.message);
        return reject(error);
      }
      if (stderr) {
        console.warn("⚠️ Whisper stderr:", stderr);
      }

      console.log("✅ Whisper 실행 완료");
      resolve(stdout);
    });
  });
}

async function formatWhisperResponse(response) {
  console.log("response 내용: ", response);

  const lines = response.split("\n").filter((l) => l.trim() !== "");
  const blocks = lines.map((line, idx) => {
    // [00:00:00 --> 00:00:05] 발언
    const match = line.match(
      /\[(\d{2}:\d{2}:\d{2})(?:\.\d{1,3})? --> (\d{2}:\d{2}:\d{2})(?:\.\d{1,3})?\]\s*(.*)/
    );
    if (!match) return null;

    const [_, start, end, speech] = match;
    return `${idx + 1}\n${start} --> ${end}\n${speech}`;
  });

  console.log("🔥 SRT 블록 배열:", blocks);

  return blocks.filter(Boolean).join("\n\n");
}

async function sortSRTByTime(srtArray) {
  return srtArray.sort((a, b) => {
    const startA = a.time.split(" --> ")[0];
    const startB = b.time.split(" --> ")[0];

    const toSeconds = (t) => {
      const [hh, mm, ss] = t.split(":").map(Number);
      return hh * 3600 + mm * 60 + ss;
    };

    return toSeconds(startA) - toSeconds(startB);
  });
}

async function buildSrtString(srtArray) {
  return srtArray
    .map((item, index) => {
      return `${index + 1}\n${item.time}\n${item.speaker}: ${item.speech}\n`;
    })
    .join("\n");
}

async function finalizeSRT(allSRTResults) {

  const sortedSrt = await sortSRTByTime(allSRTResults);
  const srtString = await buildSrtString(sortedSrt);

  return srtString
}

module.exports = { callWhisperCPP, formatWhisperResponse, sortSRTByTime, finalizeSRT }