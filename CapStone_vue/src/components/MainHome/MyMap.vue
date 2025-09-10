<template>
  <div class="mymap-container">
    <!-- 사이드바 -->
    <MainHomeSideBar />

    <!-- 콘텐츠 영역 -->
    <main class="content">
      <div class="lottie-container">
        <!-- 첫 번째 Lottie 애니메이션 (배경) -->
        <DotLottieVue
          class="background-lottie"
          :class="{ 'lottie-appear': showLottie }"
          autoplay
          loop
          speed="0.9"
          src="https://lottie.host/30c86abc-20f9-4679-a194-9b287cd1f8e7/DMPnrTxjuW.lottie"
        />
        
        <!-- 두 번째 Lottie 애니메이션 (중앙) -->
        <DotLottieVue
          class="center-lottie"
          :class="{ 'lottie-appear': showLottie }"
          autoplay
          loop
          speed="0.7"
          src="https://lottie.host/2e9e330c-4273-443b-b4d2-a7e5dcad051d/CeXM6eCbtf.lottie"
        />
        
        <!-- 프로젝트 생성 버튼 -->
        <button 
          class="create-project-button"
          @click="createAndOpenMap"
        >
          <span class="button-text">프로젝트 생성</span>
          <div class="button-glow"></div>
        </button>
      </div>

      <!-- 주제 선택 모달 -->
      <div
        v-if="showTopicModal"
        class="modal-overlay"
        @click.self="handleCancel"
      >
        <div class="modal-content">
          <h3 class="modal-title">주제를 선택하세요</h3>

          <form @submit.prevent="handleTopicSubmit">
            <div class="radio-group">
              <label
                v-for="topic in topicOptions"
                :key="topic"
                class="radio-label"
              >
                <input
                  type="radio"
                  name="selectedTopic"
                  :value="topic"
                  v-model="selectedTopic"
                />
                {{ topic }}
              </label>
            </div>

            <div class="modal-buttons">
              <button type="submit" class="confirm-btn">확인</button>
              <button type="button" class="cancel-btn" @click="handleCancel">
                취소
              </button>
            </div>
          </form>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
import { onMounted, onBeforeUnmount, ref } from "vue";
import MainHomeSideBar from "./MainHomeSideBar.vue";
import { DotLottieVue } from "@lottiefiles/dotlottie-vue";
import { connectSocket } from "../socket/socket";
import { createProject } from "../../api/projectApi";
import { useRouter } from "vue-router";

export default {
  name: "MyMap",
  components: {
    MainHomeSideBar,
    DotLottieVue,
  },
  setup() {
    const router = useRouter();

    // 세션에서 userId 가져오기
    const userId = sessionStorage.getItem("userId");

    // ✅ 주제 선택 관련 상태
    const showTopicModal = ref(false);
    const selectedTopic = ref("");
    const topicOptions = [
      "관광 및 지역자원",
      "의학 및 의료정보",
      "법률 및 행정",
    ];

    // Lottie 등장 애니메이션 상태
    const showLottie = ref(false);

    const handleTopicSubmit = async () => {
      if (!selectedTopic.value) {
        alert("주제를 선택해주세요.");
        return;
      }

      try {
        if (!userId) {
          console.error("❌ 사용자 ID가 없습니다.");
          return;
        }

        const newProject = await createProject(userId, selectedTopic.value);

        if (newProject && newProject.project_id) {
          console.log("🟢 새 프로젝트 생성 완료:", newProject.project_id);
          router.push(`/MindMap/${newProject.project_id}`);
        }
      } catch (error) {
        console.error("❌ 프로젝트 생성 중 오류 발생:", error);
      } finally {
        showTopicModal.value = false;
      }
    };

    const handleCancel = () => {
      selectedTopic.value = "";
      showTopicModal.value = false;
    };

    const createAndOpenMap = () => {
      showTopicModal.value = true;
    };

    // 휠 이벤트 처리를 위한 변수
    let isScrolling = false;
    let scrollTimeout;

    // 휠 이벤트 핸들러
    const handleWheel = (event) => {
      // 이미 스크롤 중이면 추가 이벤트 무시
      if (isScrolling) return;

      // 아래로 스크롤하는 경우 (deltaY가 양수)
      if (event.deltaY > 50) {
        isScrolling = true;

        // 연속된 스크롤 이벤트 방지를 위한 디바운싱
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
          console.log("아래로 스크롤 감지, Recent 페이지로 이동합니다");
          router.push("/Recent");

          // 스크롤 상태 초기화 (다음 페이지에서 정상 작동하도록)
          setTimeout(() => {
            isScrolling = false;
          }, 500);
        }, 300);
      }
    };

    onMounted(() => {
      connectSocket(() => {
        console.log("소켓 연결 완료");
      });

      // Lottie 진입 애니메이션 트리거
      setTimeout(() => {
        showLottie.value = true;
      }, 130);

      // 휠 이벤트 리스너 등록
      window.addEventListener("wheel", handleWheel, { passive: false });
    });

    onBeforeUnmount(() => {
      // 컴포넌트 언마운트 시 이벤트 리스너 제거 및 타이머 정리
      window.removeEventListener("wheel", handleWheel);
      clearTimeout(scrollTimeout);
    });

    return {
      createAndOpenMap,
      showTopicModal,
      selectedTopic,
      topicOptions,
      handleTopicSubmit,
      handleCancel,
      showLottie,
    };
  },
  mounted() {
    // 페이지 로드 시 소켓 연결
    connectSocket(() => {
      console.log("소켓 연결 완료");
    });
  },
};
</script>

<style scoped>
.mymap-container {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  position: relative;
}

.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  margin-left: 0;
  box-sizing: border-box;
}

.lottie-container {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0A0E1F 0%, #1A2044 100%);
}

/* Lottie 등장 애니메이션 (fade + scale) */
.background-lottie,
.center-lottie {
  opacity: 0;
  transform: scale(0.96);
  transition: opacity 1s cubic-bezier(0.23,1,0.32,1), transform 1s cubic-bezier(0.23,1,0.32,1);
}
.lottie-appear {
  opacity: 1 !important;
  transform: scale(1) !important;
}

/* 배경 Lottie 애니메이션 */
.background-lottie {
  position: absolute;
  top: 0;
  left: 0;
  width: 100% !important;
  height: 100% !important;
  z-index: 1;
}

/* 중앙 Lottie 애니메이션 - 크기 증가 */
.center-lottie {
  position: relative;
  width: 550px !important;
  height: 550px !important;
  z-index: 2;
}

/* 🌌 조화로운 우주 테마의 프로젝트 생성 버튼 */
.create-project-button {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  
  /* 기본 스타일 */
  padding: 16px 32px;
  border: none;
  border-radius: 50px;
  font-family: 'Inter', 'SF Pro Display', -apple-system, sans-serif;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.5px;
  cursor: pointer;
  overflow: hidden;
  
  /* 🎨 조화로운 블루-퍼플 그라데이션 (지구본과 우주 테마에 어울림) */
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  
  /* 🌟 은은한 그림자 효과 */
  box-shadow: 
    0 8px 32px rgba(102, 126, 234, 0.25),
    0 0 0 1px rgba(255, 255, 255, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.15);
    
  /* 🎭 부드러운 애니메이션 */
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  
  /* 3D 효과 */
  transform-style: preserve-3d;
}

/* 버튼 텍스트 */
.button-text {
  position: relative;
  z-index: 2;
  display: block;
}

/* 글로우 효과 */
.button-glow {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, transparent, rgba(255, 255, 255, 0.15), transparent);
  transform: translateX(-100%) skewX(-15deg);
  transition: transform 0.6s ease;
  z-index: 1;
}

/* 호버 효과 */
.create-project-button:hover {
  /* 🔮 더 생동감 있는 그라데이션 */
  background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
  
  /* ✨ 강화된 그림자 */
  box-shadow: 
    0 12px 48px rgba(102, 126, 234, 0.35),
    0 0 0 1px rgba(255, 255, 255, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.2);
    
  /* 🚀 부드러운 상승 효과 */
  transform: translateX(-50%) translateY(-4px) scale(1.02);
}

/* 호버 시 글로우 애니메이션 */
.create-project-button:hover .button-glow {
  transform: translateX(100%) skewX(-15deg);
}

/* 클릭 효과 */
.create-project-button:active {
  transform: translateX(-50%) translateY(-2px) scale(0.98);
  box-shadow: 
    0 6px 24px rgba(102, 126, 234, 0.3),
    0 0 0 1px rgba(255, 255, 255, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.15);
}

/* 🎯 은은한 펄스 애니메이션 */
@keyframes softPulse {
  0% {
    box-shadow: 0 8px 32px rgba(102, 126, 234, 0.25);
  }
  50% {
    box-shadow: 0 8px 32px rgba(102, 126, 234, 0.35);
  }
  100% {
    box-shadow: 0 8px 32px rgba(102, 126, 234, 0.25);
  }
}

.create-project-button {
  animation: softPulse 3s ease-in-out infinite;
}

/* 모달 관련 스타일 - 두 번째 코드의 간단한 디자인 적용 */
.modal-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(10, 14, 31, 0.85);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}

.modal-content {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background-color: #1a2044;
  border-radius: 12px;
  padding: 24px 32px;
  box-shadow: 0 0 20px rgba(78, 125, 247, 0.4);
  color: white;
  min-width: 320px;
  text-align: left;
}

.modal-title {
  text-align: center;
  font-weight: bold;
  font-size: 18px;
  margin-bottom: 16px;
  color: #3d7bff;
}

.radio-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 20px;
  padding-left: 1rem;
}

.radio-label {
  font-size: 14px;
}

.radio-label input[type="radio"] {
  margin-right: 5px;
  transform: translateY(1.5px);
  accent-color: #ff9d2a;
}

.radio-label input[type="radio"]:focus {
  outline: none;
  box-shadow: none;
}

.modal-buttons {
  display: flex;
  justify-content: center;
  gap: 15px;
  margin-top: 25px;
}

.confirm-btn,
.cancel-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-weight: bold;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 0 10px rgba(78, 125, 247, 0.3);
}

/* 확인 버튼 - 네온 느낌 */
.confirm-btn {
  background: linear-gradient(135deg, #4e7df7, #6c9dff);
  color: white;
}

.confirm-btn:hover {
  background: linear-gradient(135deg, #6c9dff, #4e7df7);
  box-shadow: 0 0 15px rgba(78, 125, 247, 0.7);
}

/* 취소 버튼 - 진한 회색 + 약간의 블루톤 */
.cancel-btn {
  background-color: #2e2e2e;
  color: #ccc;
}

.cancel-btn:hover {
  background-color: #444;
  color: #fff;
}

/* 반응형 디자인 */
@media (max-width: 1200px) {
  .center-lottie {
    width: 500px !important;
    height: 500px !important;
  }
}

@media (max-width: 768px) {
  .content {
    margin-left: 0;
    padding-left: 0;
  }

  .center-lottie {
    width: 400px !important;
    height: 400px !important;
  }

  .create-project-button {
    bottom: 60px;
    padding: 14px 28px;
    font-size: 15px;
  }

  .modal-content {
    margin: 20px;
    min-width: auto;
    width: calc(100% - 40px);
    max-width: 400px;
  }
}

@media (max-width: 480px) {
  .center-lottie {
    width: 300px !important;
    height: 300px !important;
  }
  
  .create-project-button {
    bottom: 40px;
    padding: 12px 24px;
    font-size: 14px;
  }
}
</style>