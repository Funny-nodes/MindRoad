const express = require("express");
const { upload } = require("../config/multerConfig");
const audioController = require("../controllers/audioController");

module.exports = (io) => {
  const router = express.Router();
  const { uploadMeetingAudio, uploadRealTimeAudio } = audioController(io);

  // 올바른 미들웨어 체인 구성
  router.post( "/meeting", upload.single("audio"), uploadMeetingAudio);

  router.post( "/realTime", upload.single("audio"), uploadRealTimeAudio);

  return router;
};
