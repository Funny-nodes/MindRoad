const path = require("path");
const fs = require("fs");

const { mixAudio } = require("./audioMix");
const { convertToWhisperWav } = require("./convertToWhisperWav");
const {
  makeSafeNickname,
  convertSegmentsToSRTJson,
} = require("./safeNickname");
const { askOpenAI } = require("./callOpenAI"); // 회의록 요약
const { deleteFiles } = require("./deleteFiles");
const nodeService = require("../nodeService/nodeService");
const { callSTT } = require("./callSTT");
const {
  extractRealtimeKeywordsFromColab,
} = require("./realtimeKeywordsFromColab"); // ✅ 실시간 키워드 추출

const audioFolder = path.join(__dirname, "../../../storage/audio");
const tempAudioFolder = path.join(__dirname, "../../../storage/temp_audio");

exports.processIndividualFile = async (
  roomAudioBuffers,
  roomId,
  isRealTime
) => {
  const userSpeech = {}; // { nickname: [{time,speaker,speech}, ...] }
  const speakerNames = []; // ["닉1","닉2",...]

  try {
    if (!roomAudioBuffers || roomAudioBuffers.length === 0) return;

    const outputWavPaths = await Promise.all(
      roomAudioBuffers.map(async (userObject) => {
        const outputPath = userObject.inputPath.replace(
          path.join("temp_audio"),
          path.join("audio")
        );
        const wavPath = await convertToWhisperWav(
          userObject.inputPath,
          outputPath
        );
        return { nickname: userObject.nickname, wavPath };
      })
    );

    const sttResults = await callSTT(outputWavPaths.map((o) => o.wavPath));

    // STT 결과 적재
    for (const stt of sttResults.results) {
      const nickname = stt.nickname;
      userSpeech[nickname] = stt.segments;
      speakerNames.push(nickname);
    }

    // 프로젝트/노드 로드
    const projectId = roomId.split("-").pop();
    const { data } = await nodeService.getMindmapByProjectId(projectId);
    const nodeData = Array.isArray(data) ? data : [];

    const projectService = require("../projectService/projectService"); // 경로는 실제 위치에 맞춰 수정
    let category = await projectService.getProjectCategoryName(projectId);
    console.log(`🎯 Project ${projectId} category=${category}`);

    // 하나의 타임라인 SRT JSON으로 병합
    const formattedSpeech = convertSegmentsToSRTJson(userSpeech);
    console.log(
      "📌 변환된 SRT JSON:",
      JSON.stringify(formattedSpeech, null, 2)
    );

    let openAIResponse;
    let addedNodes = null;

    if (isRealTime) {
      // ✅ 실시간: 코랩 서버(/mindmap/suggest)로 키워드만 추출
      const { raw, keywords } = await extractRealtimeKeywordsFromColab({
        srtJson: formattedSpeech, // [{time,speaker,speech}, ...]
        nodeData, // DB 노드 스냅샷
        baseURL: process.env.MINDROAD_BASE_URL || "https://mind-road2.loca.lt",
        category,
        maxK: 2,
        debug: true,
        requirePlacementParent: false, // 부모 미확정이면 루트 폴백
      });
      openAIResponse = raw;

      if (keywords?.length) {
        // keywords: [{ name, parent_key }]
        addedNodes = await nodeService.addKeywordsAsNodes(projectId, keywords);
      }
    } else {
      // ✅ 회의록 요약: 닉네임별 맵 불필요, SRT JSON 배열 그대로 전달
      openAIResponse = await askOpenAI(
        formattedSpeech, // ← 배열 그대로
        speakerNames,
        nodeData,
        false
      );
      // 필요 시 openAIResponse.minutes.keywords를 이용한 추가 삽입 로직을 여기에 붙여도 됨

      if (nodeData && nodeData.length > 0) {
        openAIResponse.rootNode = nodeData[0];
      }
    }

    

    const audioType = isRealTime ? "realTime" : "meeting";
    const userTempFolder = path.join(tempAudioFolder, audioType, roomId);
    const userAudioFolder = path.join(audioFolder, audioType, roomId);

    console.log("🧪 userAudioFolder:", userAudioFolder);
    console.log("🧪 userTempFolder:", userTempFolder);

    if (!fs.existsSync(userAudioFolder)) {
      fs.mkdirSync(userAudioFolder, { recursive: true });
    }

    const mixedAudioPath = await mixAudio(userAudioFolder, userAudioFolder);

    

    // 파일 삭제
    deleteFiles(userTempFolder);
    deleteFiles(userAudioFolder); // 혼합 파일까지 지워질 수 있으니 필요 시 분리 정리 유틸 권장

    return { openAIResponse, mixedAudioPath, addedNodes };
  } catch (error) {
    console.error("❌ 음성 인식 및 분석 오류:", error);
    throw new Error("음성 인식 및 분석 중 오류 발생");
  }
};

exports.mixAndConvertAudio = async (roomId, roomAudioBuffers) => {
  try {
    if (roomAudioBuffers.length === 1) {
      return roomAudioBuffers[0];
    }
    const mixedAudioPath = await mixAudio(audioFolder, audioFolder);
    return mixedAudioPath;
  } catch (error) {
    console.error("❌ 오디오 믹싱 및 변환 오류:", error);
    throw new Error("오디오 믹싱 및 변환 중 오류 발생");
  }
};

exports.processAudioFile = async (mp3Path, speakerCount) => {
  try {
    const fileName = path.basename(mp3Path, ".wav");
    let speakerNames = fileName.includes("+")
      ? fileName.split("+").join(", ")
      : fileName;

    const clovaResponse = await callClovaSpeechAPI(mp3Path, speakerCount);
    const openAIResponse = await askOpenAI(clovaResponse, speakerNames);

    deleteFiles(tempAudioFolder);
    deleteFiles(audioFolder);

    return { clovaResponse, openAIResponse };
  } catch (error) {
    console.error("❌ 음성 인식 및 분석 오류:", error);
    throw new Error("오디오 인식/분석 중 오류 발생");
  }
};

exports.processRealTimeAudio = async (mp3Path, mindMap) => {
  try {
    const clovaResponse = await callClovaSpeechAPI(mp3Path);
    const nodeOpenAIResponse = await nodeOpenAI(clovaResponse, mindmap);
    return { clovaResponse, nodeOpenAIResponse };
  } catch (error) {
    console.error("❌ 음성 인식 및 분석 오류:", error);
    throw new Error("오디오 인식/분석 중 오류 발생");
  }
};

exports.convertToMP3 = async (inputPath) => {
  const fileName = path.basename(inputPath, ".wav");
  const outputPath = path.join(audioFolder, `${fileName}.mp3`);
  try {
    return await convertToMP3(inputPath, outputPath);
  } catch (error) {
    console.error("❌ MP3 변환 오류:", error);
    throw new Error("MP3 변환 중 오류 발생");
  }
};
