const fs = require("fs")
const path = require("path")
const { exec } = require("child_process");
const { stderr } = require("process");

async function callWhisperCPP(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error("❌ 파일이 존재하지 않습니다: " + filePath);
  }

  const whisperBinary = path.resolve(__dirname, "../../../whisper.cpp/build/bin/Release/whisper-cli.exe"); // Whisper 실행 파일 경로
  const modelPath = path.resolve(
    __dirname,
    "../../../whisper.cpp/models/ggml-base.bin"
  ); // 모델 경로

  const command = `"${whisperBinary}" -m "${modelPath}" -f "${filePath}" --language ko`;

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

module.exports = { callWhisperCPP }