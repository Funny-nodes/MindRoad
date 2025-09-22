const fs = require("fs")
const path = require("path")
const axios = require("axios")

exports.callSTT = async(outputWavPath) =>{
  if (!outputWavPath) {
    throw new Error("❌ wav 파일이 존재하지 않습니다: " + outputWavPath);
  }


  const paths = Array.isArray(outputWavPath)? outputWavPath : [outputWavPath];
  const FormData = require("form-Data")
  const formData = new FormData();

  for (const wavPath of paths) {
    if (!fs.existsSync(wavPath)) {
      throw new Error("❌ wav 파일이 존재하지 않습니다: " + wavPath);
    }

    formData.append("files", fs.createReadStream(wavPath));
  }

  const API_URL = process.env.LOCALTUNNEL;
  try {
    const start = Date.now();
    const response = await axios.post(
      `${API_URL}/stt_multi`,
      formData,
      { headers: formData.getHeaders() }
    );
    console.log("✅ STT 결과:", response.data);
    const end = Date.now();
    console.log(`⏱ STT 요청 시간: ${(end - start) / 1000}초`);
    
    const result = response.data
    return result;
  } catch (err) {
    console.error("❌ 요청 실패:", err.response?.data || err.message);
  }
}