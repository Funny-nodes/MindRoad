<template>
  <div id="app">
    <div v-if="!joined" class="login-container">
      <div class="login-wrapper">
        <div class="logo-section">
          <div class="brand-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="22" stroke="currentColor" stroke-width="2"/>
            </svg>
            <i class="fa-solid fa-microphone-lines"></i>
          </div>
          <h1 class="brand-title">VoiceHub</h1>
          <p class="brand-subtitle">Professional Voice Conference</p>
        </div>

        <div class="login-form">
          <button @click="joinRoom" :disabled="joining" class="join-btn">
            {{ joining ? "연결 중..." : "회의실 입장" }}
          </button>
        </div>
      </div>
    </div>

    <div v-else class="meeting-interface">
      <!-- 상단 헤더 - 일반 정적 위치 -->
      <header class="meeting-header">
        <div class="header-content">
          <div class="room-section">
            <span class="room-label">Room {{ displayRoomId }}</span>
            <div class="live-badge">
              <div class="live-dot"></div>
              <span>LIVE</span>
            </div>
          </div>
          
          <div class="header-spacer"></div>
          
          <div class="controls-section">
            <div class="participant-indicator">
              <i class="fa-solid fa-user-group" style="font-size: 13px;"></i>
              <span class="count-text">{{ participants.length }}명</span>
            </div>
            <button @click="leaveRoom()" class="exit-button" :class="connectionStatus.toLowerCase()">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6.62 10.79c1.44 2.83 3.76 5.15 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/>
              </svg>
            </button>
          </div>
        </div>
      </header>

      <!-- 메인 콘텐츠 - 세로 배치, 정적 위치 -->
      <main class="meeting-content">

        <!-- 참여자 섹션 -->
        <section class="content-section participants-section">
          
          
          <div class="participants-container">
            <div
                v-for="id in participants"
                :key="id"
                class="participant-item"
                :class="{ 'current-user': id === currentUserId }"
              >
              <div class="participant-avatar">
                <div class="avatar-circle">{{ getUserDisplayName(id).charAt(0) }}</div>
                <div class="status-indicator"></div>
              </div>
              
              <div class="participant-info">
                <div class="participant-name">
                  {{ getUserDisplayName(id) }}
                  <span v-if="id === currentUserId" class="you-badge">You</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 오디오 컨트롤 섹션 -->
        <section class="content-section audio-section">
          <div class="section-header">
            <h2 class="section-title">오디오 설정</h2>
            <span class="section-badge" :class="{ muted: isMuted }">
              {{ isMuted ? "음소거" : "활성" }}
            </span>
          </div>
          
          <div class="audio-controls">
            <button @click="toggleMute" class="audio-toggle-btn" :class="{ active: !isMuted }">
              <div class="btn-icon">
                <i v-if="isMuted" class="fa-solid fa-volume-low" style="font-size: 16px;"></i>
                <i v-else class="fa-solid fa-volume-xmark" style="font-size: 16px;"></i>
              </div>
              <span>{{ isMuted ? "음소거 해제" : "음소거" }}</span>
            </button>
            
            <div class="control-group">
              <label class="control-label">오디오 장치</label>
              <select
                v-model="selectedAudioDevice"
                @change="changeAudioDevice"
                :disabled="isRecording"
                class="device-select"
              >
                <option v-for="device in audioDevices" :key="device.deviceId" :value="device.deviceId">
                  {{ device.label || `장치 ${device.deviceId.substr(0, 8)}...` }}
                </option>
              </select>
            </div>
            
            <div class="control-group">
              <label class="control-label">음성 레벨</label>
              <div class="audio-level">
                <div class="level-bar">
                  <div class="level-fill" :style="{ width: `${audioLevel}%` }"></div>
                </div>
                <span class="level-text">{{ Math.round(audioLevel) }}%</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 녹음 섹션 -->
        <section class="content-section recording-section">
          <div class="section-header">
            <h2 class="section-title">회의 녹음</h2>
            <span class="section-badge" :class="{ active: isRecording }">
              {{ isRecording ? "녹음 중" : "대기" }}
            </span>
          </div>
          
          <div class="recording-controls">
            <button
              @click="toggleRecording"
              class="record-button"
              :class="{ 
                recording: isRecording,
                disabled: isProcessingRecording 
              }"
              :disabled="isProcessingRecording"
            >
              <div class="record-icon">
                <svg v-if="isRecording" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12" rx="2"/>
                </svg>
                <svg v-else width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="12" r="10"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              </div>
              
              <div class="record-info">
                <span class="record-title">{{ isRecording ? "녹음 중지" : "녹음 시작" }}</span>
                <span class="record-desc">{{ isRecording ? "클릭하여 중지" : "회의 내용을 기록합니다" }}</span>
              </div>
            </button>
          </div>
        </section>

        <!-- 회의록 섹션 -->
        <section class="content-section transcript-section">
          <div class="section-header">
            <h2 class="section-title">회의록</h2>
            <div class="header-actions" v-if="!isLoading">
              <button class="action-btn" @click="downloadAudio">
                <i class="fa-solid fa-file-audio" style="font-size: 14px;"></i>
                음성파일
              </button>
              <button class="action-btn primary" @click="downloadPDF">
                <i class="fa-solid fa-file" style="font-size: 13.5px;"></i>
                PDF
              </button>
            </div>
          </div>
          
          <div class="transcript-body">
            <!-- 로딩 상태 -->
            <div v-if="isLoading" class="loading-container">
              <div class="loading-animation">
                <DotLottieVue
                  style="height: 100px; width: 100px"
                  autoplay
                  loop
                  speed="1.5"
                  :src="lottieUrl"
                />
              </div>
              <div class="loading-info">
                <h3>AI 회의록 생성 중</h3>
                <p>음성 데이터를 분석하여 회의록을 작성하고 있습니다</p>
              </div>
              <div class="loading-progress">
                <div class="progress-bar">
                  <div class="progress-fill"></div>
                </div>
              </div>
            </div>

            <!-- 회의록 내용 -->
            <div v-else class="transcript-content" v-html="meetingContent"></div>
          </div>
        </section>
      </main>

      <!-- 재연결 버튼 -->
      <div v-if="connectionStatus === 'disconnected'" class="reconnect-overlay">
        <button @click="reconnect" class="reconnect-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M4 12a8 8 0 0 1 8-8V2.5L16 6l-4 3.5V8a6 6 0 1 0 6 6h2a8 8 0 0 1-16 0z"/>
          </svg>
          다시 연결
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import io from "socket.io-client";
import axios from "axios";
import uploadAudio from "../audio/uploadAudio";
import meetingContent from "../audio/meetingContent";
import meetingPDF from "../audio/meetingPDF";
import { fetchHeaderBlob } from "../audio/fetchHeaderBlob";
import { DotLottieVue } from "@lottiefiles/dotlottie-vue";

export default {
  name: "AudioMeetingApp",
  components: {
    DotLottieVue,
  },
  props: {
    // roomId props 추가
    autoJoinRoomId: {
      type: String,
      default: "",
    },
  },
  data() {
    return {
      lottieUrl:
        "https://lottie.host/40e2218d-5c55-4588-908a-02eb89cdb36a/7109HrIh1Q.lottie",
      socket: null,
      activeBufferIndex: null,
      currentUserId: null,
      peerConnections: {},
      localStream: null,
      isPoliteMap: [],
      isCreatingOfferMap: {},
      remoteStreams: {},
      audioElements: {},
      roomId: "",
      participants: [],
      joined: false,
      joining: false,
      isMuted: false,
      audioDevices: [],
      selectedAudioDevice: "",
      sttProcess: null,
      audioLevel: 0,
      speakingParticipants: {},
      connectionStatus: "disconnected",
      audioContext: null,
      audioAnalyser: null,
      retryAttempts: {},
      maxRetries: 3,
      isRecording: false, // 녹음 상태 관리
      mediaRecorder: null, // MediaRecorder 인스턴스
      recordedChunks: [], // 녹음된 데이터
      temporaryChunks: [],
      uploadInterval: null,
      meetingContent: "<p style='color: #bbb;'>아직 회의록이 없습니다.</p>", // 기본 텍스트
      participantNicknames: {}, // 참가자 닉네임 저장용 객체 추가
      rootNode: null,
      audioBlob: null,
      headerBlob: null,
      pdfBlob: null,
      isProcessingRecording: false, // 녹음 처리 중이면 true
      isLoading: false,
    };
  },

  // autoJoinRoomId가 있으면 컴포넌트 마운트 시 자동으로 방에 참여
  async mounted() {
    // 🔥 Lottie 애니메이션 사전 로딩 추가
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.href = this.lottieUrl;
    document.head.appendChild(link);

    if (this.autoJoinRoomId) {
      // props로 받은 roomId를 바로 설정
      this.roomId = this.autoJoinRoomId;
      // 자동 참가는 하지 않고, 사용자가 버튼을 클릭할 때만 참가
    }

    window.addEventListener("popstate", this.handlePopState);
  },

  beforeUnmount() {
    window.removeEventListener("popstate", this.handlePopState);
    this.leaveRoom(); // 컴포넌트가 파괴될 때도 방 떠나기
  },

  computed: {
    // 현재 사용자의 닉네임 (MainHomeSideBar와 유사한 방식)
    userNickname() {
      return (
        sessionStorage.getItem("userNickname") ||
        sessionStorage.getItem("userEmail") ||
        "익명 사용자"
      );
    },

    // 사용자가 로그인 상태인지 확인
    isLoggedIn() {
      return (
        sessionStorage.getItem("isLoggedIn") === "true" &&
        sessionStorage.getItem("userEmail") !== null
      );
    },

    // 표시용 방 번호 (숫자만)
    displayRoomId() {
      return this.roomId.replace("project-audio-", "");
    },
  },
  methods: {
    handlePopState() {
      console.log("뒤로가기 감지");
      this.leaveRoom();
    },

    // 사용자의 닉네임을 가져오는 함수
    getUserDisplayName(userId) {
      // 현재 사용자인 경우 세션 스토리지에서 닉네임 가져오기
      if (userId === this.currentUserId) {
        return this.userNickname;
      }
      // 다른 참가자의 경우 저장된 닉네임 사용하거나 ID 표시
      return this.participantNicknames[userId] || userId;
    },

    // joinRoom 메서드에서 방 번호 검증 부분 수정
    async joinRoom() {
      try {
        // autoJoinRoomId를 사용
        if (this.autoJoinRoomId) {
          this.roomId = this.autoJoinRoomId;
        }

        // 방 번호가 있는지 확인
        if (!this.roomId) {
          alert("방 번호가 필요합니다.");
          return;
        }

        this.joining = true;
        console.log("Joining room:", this.roomId);
        this.isMuted = false;
        await this.setupAudioStream();
        await this.setupSignaling();
        this.joined = true;
        this.connectionStatus = "Connected";
      } catch (error) {
        console.error("Failed to join room:", error);
        alert(`Failed to join room: ${error.message}`);
      } finally {
        this.joining = false;
      }
    },

    async setupAudioStream() {
      try {
        // 먼저 기본 오디오 스트림을 얻어 권한 확보
        const initialStream = await navigator.mediaDevices.getUserMedia({
          audio: true,
          video: false,
        });

        // 권한을 얻은 후 디바이스 목록 조회
        const devices = await navigator.mediaDevices.enumerateDevices();
        this.audioDevices = devices.filter(
          (device) => device.kind === "audioinput"
        );

        // 현재 사용 중인 디바이스 찾기
        const currentTrack = initialStream.getAudioTracks()[0];
        const currentDevice = this.audioDevices.find(
          (device) => device.label === currentTrack.label
        );

        // 현재 디바이스 선택
        if (currentDevice) {
          this.selectedAudioDevice = currentDevice.deviceId;
        }

        // 초기 스트림 정리
        initialStream.getTracks().forEach((track) => track.stop());

        // 선택된 디바이스로 새 스트림 생성
        const constraints = {
          audio: this.selectedAudioDevice
            ? { deviceId: { exact: this.selectedAudioDevice } }
            : true,
          video: false,
        };

        this.localStream = await navigator.mediaDevices.getUserMedia(
          constraints
        );

        // 오디오 분석기 설정
        this.audioContext = new (window.AudioContext ||
          window.webkitAudioContext)();
        const audioSource = this.audioContext.createMediaStreamSource(
          this.localStream
        );
        this.audioAnalyser = this.audioContext.createAnalyser();
        audioSource.connect(this.audioAnalyser);

        this.startAudioLevelMonitoring();
      } catch (error) {
        console.error("Error setting up audio stream:", error);
        throw new Error(`Microphone access denied: ${error.message}`);
      }
    },

    startAudioLevelMonitoring() {
      if (!this.audioAnalyser) return;

      const dataArray = new Uint8Array(this.audioAnalyser.frequencyBinCount);
      const monitor = () => {
        this.audioAnalyser.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        this.audioLevel = (average / 255) * 100;
        requestAnimationFrame(monitor);
      };
      monitor();
    },

    // 음성 녹음 시작
    // 녹음 시작/중지 토글 메서드
    toggleRecording() {
      this.isRecording = !this.isRecording;

      if (this.isRecording) {
        this.socket.emit("start-recording", this.roomId);

        console.log("🎙️ 녹음 시작");
      } else {
        this.socket.emit("stop-recording", this.roomId);

        console.log("🎙️ 녹음 중지");
      }
    },

    async checkRecording() {
      // 클라이언트에서 녹음 시작/중지 처리
      if (this.isRecording) {
        // 녹음 시작 함수
        console.log(`🎙️ 녹음시작 - WebRTC.vue:270`);
        this.startRecording(); // 녹음 시작
      } else {
        // 녹음 중지 함수
        console.log(`🎙️ 녹음중지 - WebRTC.vue:275`);
        this.stopRecording();
      }
    },

    // 녹음 시작 메서드
    async startRecording() {
      if (!this.localStream) return;

      this.recordedChunks = [];

      try {
        // 헤더 블롭을 한 번만 설정

        if (this.headerBlob == null) {
          const headerAudio = await fetchHeaderBlob();

          this.headerBlob = headerAudio;
          console.log("✅ 헤더오디오 저장완료!");

          // this.recordedChunks.push(this.headerBlob);
        }
      } catch (error) {
        console.error("헤더 오디오 로드실패:", error);
      }

      this.mediaRecorder = new MediaRecorder(this.localStream, {
        mimeType: "audio/webm; codecs=opus;",
        bitrateMode: "variable",
        audioBitsPerSecond: 64000,
      });

      this.mediaRecorder.ondataavailable = async (event) => {
        const blob = new Blob([this.headerBlob, event.data], {
          type: "audio/webm", // Blob의 MIME 타입을 설정 (여기서는 예시로 webm을 사용)
        });

        console.log(`🔄 ondataavailable: ${blob.size}bytes`);

        this.recordedChunks.push(event.data);

        // if (blob.size > 0 && this.mediaRecorder.state === "recording") {
        //   try {
        //     await uploadAudio(blob, this.roomId, this.userNickname, "realTime");
        //     console.log("✅ 업로드 성공");
        //   } catch (err) {
        //     console.error("❌ 업로드 실패:", err.message);
        //   }
        // } else {
        //   console.warn("🚫 실시간 종료");
        // }
      };

      this.uploadInterval = setInterval(async () => {
        if (this.mediaRecorder.state === "recording") {
          this.mediaRecorder.requestData(); // => 이때 ondataavailable 이벤트 발생
        }
      }, 15000);

      this.mediaRecorder.onstop = async () => {
        if (this.recordedChunks.length === 0) {
          console.error("❌ 녹음 데이터가 없습니다.");
          return;
        }

        clearInterval(this.uploadInterval);

        const blob = new Blob(this.recordedChunks, { type: "audio/webm" });
        console.log("🎤 녹음 데이터 준비 완료, 업로드 시작...");

        // 서버로 audio파일을 업로드함
        try {
          console.log(`🔄 ondataavailable: ${blob.size}bytes`);
          await uploadAudio(blob, this.roomId, this.userNickname, "meeting");
          console.log("✅ 업로드 성공!");
        } catch (error) {
          console.error("❌ 업로드 실패:", error.message);
        }
      };

      this.mediaRecorder.start();
      this.isRecording = true;
    },

    // 녹음 중지 메서드
    stopRecording() {
      if (this.mediaRecorder) {
        this.isProcessingRecording = true;
        this.isLoading = true; // 🔹 로딩 시작
        this.mediaRecorder.stop();
      }
      this.isRecording = false;
    },

    async setupSignaling() {
      const API_BASE_URL = import.meta.env.VITE_API_BASE_URL; // ✅ 환경변수 사용

      this.socket = io(`${API_BASE_URL}`, {
        transports: ["websocket"],
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
      });

      return new Promise((resolve, reject) => {
        // WebRTC.vue의 setupSignaling 메서드 내에서 수정
        this.socket.on("connect", () => {
          this.connectionStatus = "Connected";
          this.currentUserId = this.socket.id;

          // 닉네임 정보를 방 참가 이벤트와 함께 전송
          this.socket.emit("join-room", {
            roomId: this.roomId,
            userId: this.currentUserId,
            nickname: this.userNickname, // 닉네임 정보 포함
          });

          // 추가: 입장 후 즉시 닉네임 정보를 방 전체에 공유
          this.socket.emit("update-nickname", {
            roomId: this.roomId,
            userId: this.currentUserId,
            nickname: this.userNickname,
          });

          resolve();
        });

        // 닉네임 정보 동기화를 위한 이벤트 리스너 추가
        this.socket.on("sync-nicknames", (nicknames) => {
          this.participantNicknames = nicknames;
        });

        // 녹음 상태 동기화 (누군가 녹음을 시작했을 때, 종료했을때)
        this.socket.on("sync-recording", (isRecording) => {
          this.isRecording = isRecording;

          console.log(`녹음상태 변화 : ${isRecording}`);
          //녹음 시작 or 녹음 중지함수를 실행
          this.checkRecording();
        });

        this.socket.on("return-recording", async (data) => {
          const { recordingData, fileBuffer } = data;

          console.log("🟢 서버에서 녹음 데이터 수신:", recordingData);

          this.rootNode = recordingData.rootNode;

          // base64로 전달된 MP3 파일을 Blob으로 변환
          const audioBlob = new Blob(
            [
              new Uint8Array(
                atob(fileBuffer)
                  .split("")
                  .map((c) => c.charCodeAt(0))
              ),
            ],
            { type: "audio/mp3" }
          );

          // 파일을 URL로 변환
          const audioUrl = URL.createObjectURL(audioBlob);

          this.audioBlob = audioBlob;

          // 회의록 업데이트
          const report = meetingContent(recordingData);

          // 📄 회의록 PDF 생성
          const doc = await meetingPDF(recordingData);
          const pdfBlob = await doc.output("blob");
          this.pdfBlob = pdfBlob;

          const node = recordingData.rootNode;
          console.log("테스트 루트 노드: " + node);

          console.log("📄PDF 생성완료");

          const nodes = recordingData.minutes.recommendNodes;

          console.log("🟢 반환된 추천 노드: ", nodes);
          this.meetingContent = report;

          this.isProcessingRecording = false; // 🔹 완료 시 녹음 버튼 다시 활성화
          this.isLoading = false; // 🔹 회의록 수신 후 로딩 종료
        });

        this.socket.on("return-keyword", (data) => {
          const { recordingData } = data;
          const jsonString = JSON.stringify(recordingData, null, 2);
          console.log(`반환된 키워드: ${jsonString}`);
        });

        this.socket.on("connect_error", (error) => {
          this.connectionStatus = "Error";
          reject(new Error(`Connection failed: ${error.message}`));
        });

        // 기존 참가자 목록을 받았을 때
        this.socket.on(
          "existing-participants",
          async ({ participants, nicknames }) => {
            console.log("Received existing participants:", nicknames);

            // 닉네임 정보가 있으면 저장
            if (nicknames) {
              this.participantNicknames = nicknames;
            }

            this.isPoliteMap[this.currentUserId] = false;

            for (const userId of participants) {
              if (userId !== this.currentUserId) {
                console.log(
                  `협상요청 ${this.participantNicknames[userId]}님에게 진행`
                );
                await this.createPeerConnection(userId, true);
              }
            }
          }
        );

        // 새로운 참가자가 들어왔을 때
        this.socket.on(
          "new-participant",
          async ({ participantId, nickname }) => {
            console.log("New participant joined:", participantId);

            // 새 참가자의 닉네임 저장
            if (nickname) {
              this.participantNicknames[participantId] = nickname;
            }

            // 새 참가자에게는 협상요청을 안함, 새 참가자가 기존 참가자들에게 해야함.
            if (participantId !== this.currentUserId) {
              this.isPoliteMap[participantId] = true;
              //await this.createPeerConnection(participantId, false);
            }
          }
        );

        this.socket.on("room-update", ({ participants }) => {
          this.participants = participants;
        });

        // signal요청을 받게된다. handleSignal함수로 처리해줌
        this.socket.on("signal", this.handleSignal);

        this.socket.on("user-disconnected", this.handleUserDisconnected);
      });
    },

    async createPeerConnection(userId, isInitiator = false) {
      if (this.peerConnections[userId]) {
        await this.handlePeerConnectionFailure(userId);
      }

      // 새로운 유저라면 isInitiator = true이다.
      // 새 유저가 아니면 imPolite로 설정(false)
      this.isPoliteMap[userId] = isInitiator;

      const configuration = {
        iceServers: [
          {
            urls: [
              "stun:stun1.l.google.com:19302",
              "stun:stun2.l.google.com:19302",
            ],
          },
          {
            urls: "turn:your-turn-server.com",
            username: "username",
            credential: "credential",
          },
        ],
        iceTransportPolicy: "all",
        iceCandidatePoolSize: 10,
        bundlePolicy: "max-bundle",
      };

      const peerConnection = new RTCPeerConnection(configuration);
      this.peerConnections[userId] = peerConnection;

      this.localStream.getTracks().forEach((track) => {
        peerConnection.addTrack(track, this.localStream);
      });

      // creatingOfferMap 객체를 통해서 각 peerConnction에 대한 상태 관리
      if (!this.isCreatingOfferMap) this.isCreatingOfferMap = {};
      this.isCreatingOfferMap[userId] = false;

      peerConnection.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
          const remoteStream = event.streams[0];
          this.remoteStreams[userId] = remoteStream;

          const audio = new Audio();
          audio.srcObject = remoteStream;
          audio.autoplay = true;
          this.audioElements[userId] = audio;
        }
      };

      peerConnection.onicecandidate = (event) => {
        if (event.candidate) {
          this.socket.emit("signal", {
            targetId: userId,
            signal: {
              type: "candidate",
              candidate: event.candidate,
            },
          });
        }
      };

      peerConnection.onnegotiationneeded = async () => {
        try {
          if (
            this.isPoliteMap[userId] &&
            peerConnection.signalingState === "stable" &&
            !this.isCreatingOfferMap[userId]
          ) {
            console.log(
              `🌟 ${this.participantNicknames[userId]} is polite: Creating an offer.`
            );
            this.isCreatingOfferMap[userId] = true;

            const offer = await peerConnection.createOffer({
              offerToReceiveAudio: true,
              offerToReceiveVideo: false,
            });

            await peerConnection.setLocalDescription(offer);

            this.socket.emit("signal", {
              targetId: userId,
              signal: offer,
            });

            console.log("✅ Offer created and sent successfully.");
          } else {
            console.warn(
              "🚫 Negotiation skipped: Not in stable state or polite."
            );
          }
        } catch (error) {
          console.error("Negotiation failed:", error);
        } finally {
          this.isCreatingOfferMap[userId] = false;
        }
      };

      peerConnection.onconnectionstatechange = () => {
        console.log(
          `Connection state with ${userId}:`,
          peerConnection.connectionState
        );
        if (peerConnection.connectionState === "failed") {
          this.handlePeerConnectionFailure(userId);

          if (!this.retryAttempts[userId]) {
            this.retryAttempts[userId] = 0;
          }

          if (this.retryAttempts[userId] < this.maxRetries) {
            this.retryAttempts[userId]++;
            setTimeout(
              () => this.createPeerConnection(userId, isInitiator),
              1000
            );
          } else {
            delete this.retryAttempts[userId];
          }
        } else if (peerConnection.connectionState === "connected") {
          delete this.retryAttempts[userId];
        }
      };

      // if (isInitiator) {
      //   try {
      //     if (peerConnection.signalingState === "stable") {
      //         const offer = await peerConnection.createOffer({
      //           offerToReceiveAudio: true,
      //           offerToReceiveVideo: false,
      //         });
      //       await peerConnection.setLocalDescription(offer);
      //       this.socket.emit("signal", {
      //         targetId: userId,
      //         signal: offer,
      //       });
      //     }
      //   } catch (error) {
      //     console.error("Error creating offer:", error);
      //     this.handlePeerConnectionFailure(userId);
      //   }
      // }

      return peerConnection;
    },

    async handleSignal({ senderId, signal }) {
      try {
        let peerConnection = this.peerConnections[senderId];

        if (!peerConnection) {
          peerConnection = await this.createPeerConnection(senderId, false);
        }

        if (signal.type === "candidate" && signal.candidate) {
          await peerConnection.addIceCandidate(
            new RTCIceCandidate(signal.candidate)
          );
        } else if (signal.type === "offer") {
          if (peerConnection.signalingState !== "stable") {
            await Promise.all([
              peerConnection.setLocalDescription({ type: "rollback" }),
              peerConnection.setRemoteDescription(
                new RTCSessionDescription(signal)
              ),
            ]);
          } else {
            await peerConnection.setRemoteDescription(
              new RTCSessionDescription(signal)
            );
          }

          const answer = await peerConnection.createAnswer();
          await peerConnection.setLocalDescription(answer);

          this.socket.emit("signal", {
            targetId: senderId,
            signal: answer,
          });
        } else if (signal.type === "answer") {
          if (peerConnection.signalingState === "have-local-offer") {
            await peerConnection.setRemoteDescription(
              new RTCSessionDescription(signal)
            );
          }
        }
      } catch (error) {
        console.error("Error handling signal:", error);
        this.handlePeerConnectionFailure(senderId);
      }
    },

    handlePeerConnectionFailure(userId) {
      console.warn(`🚫 Cleaning up failed connection with ${userId}`);

      if (this.peerConnections[userId]) {
        this.peerConnections[userId].close();
        delete this.peerConnections[userId];
      }

      if (this.remoteStreams[userId]) {
        this.remoteStreams[userId].getTracks().forEach((track) => track.stop());
        delete this.remoteStreams[userId];
      }
      if (this.audioElements[userId]) {
        this.audioElements[userId].srcObject = null;
        delete this.audioElements[userId];
      }

      console.log(`🔄 Connection with ${userId} has been cleaned up.`);
    },

    handleUserDisconnected(userId) {
      this.handlePeerConnectionFailure(userId);
      this.participants = this.participants.filter((id) => id !== userId);
      // 닉네임 정보도 제거
      delete this.participantNicknames[userId];
    },

    async toggleMute() {
      this.isMuted = !this.isMuted;
      this.localStream.getAudioTracks().forEach((track) => {
        track.enabled = !this.isMuted;
      });
    },

    async changeAudioDevice() {
      if (this.isRecording) {
        alert(
          "현재 녹음 중입니다. 녹음을 중지한 후 오디오 장치를 변경할 수 있습니다."
        );
        return;
      }

      if (this.selectedAudioDevice) {
        try {
          // 현재 음소거 상태 저장
          const currentMuteState = this.isMuted;

          if (this.localStream) {
            this.localStream.getTracks().forEach((track) => track.stop());
          }

          const newStream = await navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: this.selectedAudioDevice } },
            video: false,
          });

          // 새 스트림에 음소거 상태 적용
          newStream.getAudioTracks().forEach((track) => {
            track.enabled = !currentMuteState;
          });

          // isMuted 상태 업데이트
          this.isMuted = currentMuteState;

          Object.values(this.peerConnections).forEach((pc) => {
            const sender = pc
              .getSenders()
              .find((s) => s.track.kind === "audio");
            if (sender) {
              sender.replaceTrack(newStream.getAudioTracks()[0]);
            }
          });

          this.localStream = newStream;

          // 오디오 컨텍스트 및 분석기 업데이트
          if (this.audioContext) {
            // 기존 연결 해제
            this.audioContext.close();

            // 새로운 오디오 컨텍스트 및 분석기 생성
            this.audioContext = new (window.AudioContext ||
              window.webkitAudioContext)();
            const audioSource =
              this.audioContext.createMediaStreamSource(newStream);
            this.audioAnalyser = this.audioContext.createAnalyser();
            audioSource.connect(this.audioAnalyser);
            this.startAudioLevelMonitoring();
          }
        } catch (error) {
          console.error("Error changing audio device:", error);
          alert("Failed to switch audio device");
        }
      }
    },

    downloadAudio() {
      if (!this.audioBlob) {
        alert("아직 음성 녹음이 존재하지 않습니다.");
        return;
      }
      const audioUrl = URL.createObjectURL(this.audioBlob);
      const link = document.createElement("a");
      link.href = audioUrl;
      link.download = `${this.roomId}_audio.mp3`;
      link.click();
      URL.revokeObjectURL(audioUrl);
    },

    downloadPDF() {
      if (!this.pdfBlob) {
        alert("아직 PDF 회의록이 존재하지 않습니다.");
        return;
      }
      const pdfUrl = URL.createObjectURL(this.pdfBlob);
      const link = document.createElement("a");

      const today = new Date();
      const year = today.getFullYear();
      const month = String(today.getMonth() + 1).padStart(2, "0");
      const day = String(today.getDate()).padStart(2, "0");
      const date = `${year}.${month}.${day}`;

      link.href = pdfUrl;
      link.download = `${date}-${this.rootNode}.pdf`;
      link.click();
      URL.revokeObjectURL(pdfUrl);
    },

    async reconnect() {
      Object.keys(this.peerConnections).forEach((userId) => {
        this.handlePeerConnectionFailure(userId);
      });

      this.joined = false;
      this.connectionStatus = "Disconnected";
      await this.joinRoom();
    },

    leaveRoom() {
      // 모든 미디어 트랙 중지
      if (this.localStream) {
        this.localStream.getTracks().forEach((track) => track.stop());
      }

      // 모든 피어 연결 종료
      Object.keys(this.peerConnections).forEach((userId) => {
        this.handlePeerConnectionFailure(userId);
      });

      // 녹음 중이라면 중지
      if (this.isRecording) {
        this.stopRecording();
      }

      // 소켓 연결 종료
      if (this.socket) {
        this.socket.emit("leave-room", this.roomId);
        this.socket.disconnect();
      }

      // 오디오 컨텍스트 종료
      if (this.audioContext) {
        this.audioContext.close();
      }

      // 상태 초기화
      this.joined = false;
      this.connectionStatus = "Disconnected";
      this.participants = [];
      this.peerConnections = {};
      this.remoteStreams = {};
      this.audioElements = {};
      this.roomId = "";
      this.participantNicknames = {}; // 참가자 닉네임 초기화 추가

      // 회의 기록 초기화 추가
      this.meetingContent =
        "<p style='color: #bbb;'>아직 회의록이 없습니다.</p>";
    },
  },
  beforeDestroy() {
    if (this.socket) {
      this.socket.disconnect();
      this.leaveRoom();
    }

    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop());
    }

    Object.keys(this.peerConnections).forEach((userId) => {
      this.handlePeerConnectionFailure(userId);
    });

    if (this.audioContext) {
      this.audioContext.close();
    }
  },
};
</script>

<style scoped>
* {
  box-sizing: border-box;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Helvetica, Arial, sans-serif;
  margin: 0;
  padding: 0;
  min-height: 100vh;
  background: #f8fafc;
  color: #1e293b;
}

/* ===== 다크모드 로그인 화면만 적용 ===== */
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
  position: relative;
  overflow: hidden;
}

/* 다크모드 배경 장식 */
.login-container::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: radial-gradient(circle at 20% 80%, rgba(59, 130, 246, 0.15) 0%, transparent 50%),
              radial-gradient(circle at 80% 20%, rgba(147, 51, 234, 0.15) 0%, transparent 50%);
  pointer-events: none;
}

.login-wrapper {
  width: 100%;
  max-width: 380px;
  text-align: center;
  position: relative;
  z-index: 10;
}

.logo-section {
  margin-bottom: 48px;
}

.brand-icon {
  position: relative;
  display: inline-flex;
  width: 80px;
  height: 80px;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  border-radius: 20px;
  align-items: center;
  justify-content: center;
  color: white;
  margin-bottom: 24px;
  box-shadow: 0 20px 40px rgba(59, 130, 246, 0.3),
              0 0 20px rgba(59, 130, 246, 0.2);
}

.brand-icon::after {
  content: '';
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  border-radius: 22px;
  z-index: -1;
  opacity: 0.3;
  animation: pulse-glow 3s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { transform: scale(1); opacity: 0.3; }
  50% { transform: scale(1.1); opacity: 0.5; }
}

.brand-icon i {
  position: absolute;
  font-size: 24px;
  color: white;
}

.brand-title {
  font-size: 2.25rem;
  font-weight: 700;
  background: linear-gradient(135deg, #ffffff, #cbd5e1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0 0 8px 0;
  letter-spacing: -0.025em;
}

.brand-subtitle {
  font-size: 1.125rem;
  color: #94a3b8;
  margin: 0;
  font-weight: 400;
}

.login-form {
  margin-bottom: 40px;
}

.join-btn {
  width: 85%;
  height: 52px;
  margin: 0 auto; 
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  box-shadow: 0 8px 32px rgba(59, 130, 246, 0.4);
}

.join-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, transparent, rgba(255, 255, 255, 0.1));
  opacity: 0;
  transition: opacity 0.3s ease;
}

.join-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(59, 130, 246, 0.5);
}

.join-btn:hover:not(:disabled)::before {
  opacity: 1;
}

.join-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
}

/* ===== 기존 라이트모드 회의 인터페이스 유지 ===== */
.meeting-interface {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  max-width: 360px;
  margin: 0 auto;
  background: white;
  box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
}

/* ===== 회의 헤더 ===== */
.meeting-header {
  height: 64px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  z-index: 50;
}

.header-content {
  height: 100%;
  padding: 0 24px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 16px;
  max-width: 100%;
}

.room-section {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 140px;
  flex-shrink: 0;
}

.room-label {
  font-weight: 600;
  color: #1e293b;
  font-size: 1.1rem;
  white-space: nowrap;
}

.live-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #fef2f2;
  color: #dc2626;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  min-width: 50px;
  justify-content: center;
  flex-shrink: 0;
}

.live-dot {
  width: 6px;
  height: 6px;
  background: #dc2626;
  border-radius: 50%;
  animation: smooth-pulse 2s ease-in-out infinite;
  flex-shrink: 0;
}

.header-spacer {
  flex: 1;
  min-width: 0;
}

.controls-section {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 100px;
  flex-shrink: 0;
  justify-content: flex-end;
}

.participant-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #64748b;
  font-weight: 500;
  min-width: 50px;
  flex-shrink: 0;
}

.count-text {
  font-size: 0.875rem;
  white-space: nowrap;
}

.exit-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.exit-button:hover {
  background: #dc2626;
  transform: scale(1.05);
}

/* ===== 메인 콘텐츠 - 통일된 흰색 배경 ===== */
.meeting-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
  background: white; /* 전체 통일된 흰색 배경 */
  overflow-y: auto;
}

.content-section {
  background: white; /* 모든 섹션 흰색 배경으로 통일 */
  position: relative;
  /* 구분을 위한 서브틀한 border만 사용 */
  border-bottom: 1px solid #f1f5f9;
}

/* 마지막 섹션은 하단 border 제거 */
.content-section:last-child {
  border-bottom: none;
}

/* ===== 섹션 헤더 - 배경 제거하고 패딩으로 구분 ===== */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 24px 16px 24px; /* 상단 패딩 증가 */
  background: white; /* 회색 배경 제거 */
  border-bottom: none; /* 헤더 하단 border 제거 */
}

.section-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 섹션별 아이콘 추가로 구분감 향상 */
.participants-section .section-title::before {
  content: "👥";
  font-size: 1rem;
}

.audio-section .section-title::before {
  content: "🎧";
  font-size: 1rem;
}

.recording-section .section-title::before {
  content: "🎙️";
  font-size: 1rem;
}

.transcript-section .section-title::before {
  content: "📝";
  font-size: 1rem;
}

.section-badge {
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 6px;
}

.section-badge.muted {
  background: #fef2f2;
  color: #dc2626;
}

.section-badge.active {
  background: #f0fdf4;
  color: #16a34a;
}

/* ===== 참여자 섹션 ===== */
.participants-container {
  padding: 0 0 0 0;
}

.participant-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  transition: all 0.2s ease;
  border-left: 3px solid transparent;
  border-radius: 0;
}

.participant-item:hover {
  background: #f8fafc;
}

.participant-item.current-user {
  background: rgba(59, 130, 246, 0.03);
  border-left-color: #3b82f6;
}

.participant-avatar {
  position: relative;
  flex-shrink: 0;
}

.avatar-circle {
  width: 40px;
  height: 40px;
  background: #e2e8f0;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: #64748b;
  font-size: 0.875rem;
}

.status-indicator {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 12px;
  height: 12px;
  background: #10b981;
  border: 2px solid white;
  border-radius: 50%;
  transition: all 0.2s ease;
}

.participant-info {
  flex: 1;
  min-width: 0;
}

.participant-name {
  font-weight: 500;
  color: #0f172a;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 6px;
}

.you-badge {
  font-size: 0.75rem;
  color: #3b82f6;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}

/* ===== 오디오 섹션 ===== */
.audio-controls {
  padding: 0 24px 20px 24px; /* 상단 패딩 제거 */
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.audio-toggle-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.875rem;
  color: #475569;
}

.audio-toggle-btn:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.audio-toggle-btn.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1e40af;
}

.btn-icon {
  flex-shrink: 0;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.control-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.device-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.875rem;
  color: #475569;
  background: white;
  cursor: pointer;
}

.device-select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.audio-level {
  display: flex;
  align-items: center;
  gap: 12px;
}

.level-bar {
  flex: 1;
  height: 4px;
  background: #f1f5f9;
  border-radius: 2px;
  overflow: hidden;
}

.level-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #059669);
  border-radius: 2px;
  transition: width 0.1s ease;
}

.level-text {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 500;
  min-width: 32px;
  text-align: right;
}

/* ===== 녹음 섹션 ===== */
.recording-controls {
  padding: 0 24px 20px 24px; /* 상단 패딩 제거 */
}

.record-button {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
  padding: 14px;
  background: white;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.record-button:hover:not(.disabled) {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.record-button.recording {
  border-color: #ef4444;
  background: #fef2f2;
}

.record-button.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.record-icon {
  width: 48px;
  height: 48px;
  background: #ef4444;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.record-button.recording .record-icon {
  animation: pulse 2s ease-in-out infinite;
}

.record-info {
  flex: 1;
  text-align: left;
}

.record-title {
  display: block;
  font-weight: 600;
  color: #0f172a;
  font-size: 0.875rem;
}

.record-desc {
  display: block;
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 2px;
}

/* ===== 회의록 섹션 ===== */
.transcript-section {
  flex: 1;
  min-height: 400px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: white;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.action-btn.primary {
  background: white;        /* 흰색 배경으로 변경 */
  border-color: #e2e8f0;    /* 회색 테두리로 변경 */
  color: #475569;           /* 회색 텍스트로 변경 */
}

.action-btn.primary:hover {
  background: #f8fafc;      /* 호버 시 연한 회색 */
  border-color: #cbd5e1;
}

.transcript-body {
  flex: 1;
  padding: 0 24px 24px 24px; /* 상단 패딩 제거 */
  min-height: 350px;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
  text-align: center;
}

.loading-animation {
  margin-bottom: 24px;
}

.loading-info h3 {
  font-size: 1.125rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 8px 0;
}

.loading-info p {
  color: #64748b;
  margin: 0 0 24px 0;
  font-size: 0.875rem;
}

.loading-progress {
  width: 200px;
}

.progress-bar {
  height: 2px;
  background: #e2e8f0;
  border-radius: 1px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 1px;
  animation: progress 2s ease-in-out infinite;
}

@keyframes progress {
  0% { width: 0; transform: translateX(-100%); }
  50% { width: 100%; transform: translateX(0); }
  100% { width: 0; transform: translateX(100%); }
}

.transcript-content {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 20px;
  min-height: 300px;
  font-size: 0.875rem;
  line-height: 1.6;
  color: #334155;
}

/* ===== 재연결 오버레이 ===== */
.reconnect-overlay {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
}

.reconnect-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
  transition: all 0.2s ease;
}

.reconnect-btn:hover {
  background: #2563eb;
  transform: translateY(-1px);
}

/* ===== 애니메이션 ===== */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes smooth-pulse {
  0%, 100% { 
    opacity: 1;
    transform: scale(1);
  }
  50% { 
    opacity: 0.6;
    transform: scale(0.95);
  }
}

/* ===== 반응형 ===== */
@media (max-width: 480px) {
  .meeting-interface {
    max-width: 100%;
    box-shadow: none;
  }
  
  .header-content {
    padding: 0 16px;
    gap: 12px;
  }
  
  .room-section {
    min-width: 120px;
  }
  
  .room-label {
    font-size: 1rem;
  }
  
  .live-badge {
    font-size: 0.7rem;
    padding: 3px 6px;
    min-width: 45px;
  }
  
  .controls-section {
    min-width: 80px;
  }
  
  .section-header {
    padding: 20px 20px 12px 20px;
  }
  
  .participant-item {
    padding: 10px 20px;
  }
  
  .audio-controls,
  .recording-controls,
  .transcript-body {
    padding: 0 20px 16px 20px;
  }
}
</style>