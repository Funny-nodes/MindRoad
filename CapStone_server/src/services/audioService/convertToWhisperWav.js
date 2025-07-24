const fs = require("fs")
const path = require("path")
const ffmpeg = require("fluent-ffmpeg")


async function convertToWhisperWav(inputPath, outputPath) {
  console.log("입력 경로 확인:", inputPath);
  console.log("출력 경로 확인:", outputPath);


  const outputWavPath = path.format({
    dir: path.dirname(outputPath),
    name: path.parse(outputPath).name,
    ext: ".wav",
  });

  console.log("변환된 출력 경로:", outputWavPath);

  const outputDir = path.dirname(outputWavPath)
  if(!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true})
    console.log(`📁 폴더 생성 완료: ${outputDir}`);
  }

  return new Promise((resolve, reject) => {
    ffmpeg(inputPath).outputOptions([
      "-acodec pcm_s16le", // 16-bit signed PCM
      "-ac 1", // mono
      "-ar 16000",
    ])
    .format("wav")
    .on("end", () => {
      console.log(`✅ Whisper용 WAV 변환 완료: ${outputWavPath}`)
      resolve(outputWavPath)
    })
    .on("error", (err) => {
      console.error(`❌ WAV 변환 중 오류 발생: ${err.message}`)
      reject(err)
    })
    .save(outputWavPath)
  })
}

module.exports = { convertToWhisperWav }