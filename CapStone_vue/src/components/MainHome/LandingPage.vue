<template>
    <div class="landing-container">
        <!-- 중앙 배경 이미지 (텍스트보다 z-index 낮게) -->
        <img
            v-if="features[currentIndex].img"
            :src="features[currentIndex].img"
            alt="Feature 배경"
            :class="['bg-image', features[currentIndex].imgClass, { 'fade-in': imageReady }]"
            :key="'img-' + currentIndex"
        />

        <!-- 중앙 텍스트 영역 (이미지 위에 보임) -->
        <div
            :class="['center-text', { 'fade-in': textReady }]"
            :key="'text-' + currentIndex"
        >
            {{ features[currentIndex].centerText }}
        </div>
        
        <div class="features">
            <div
                v-for="(feature, idx) in features"
                :key="idx"
                class="feature"
                :class="{ active: idx === currentIndex }"
                @click="goTo(idx)"
                style="cursor: pointer;"
            >
                <div class="feature-text">{{ feature.text }}</div>
                <div class="progress-bar">
                    <div
                        class="progress-fill"
                        :style="{
                          width: progresses[idx] + '%',
                          transition: idx === currentIndex ? 'width 0.2s' : 'none'
                        }"
                    ></div>
                </div>
            </div>
        </div>
        
        <!-- 하단 스크롤 안내 텍스트 및 애니메이션 화살표 추가 -->
        <div class="scroll-guide" @click="navigateToNextPage">
            <i class="fa-solid fa-arrow-down arrow"></i>
        </div>
    </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { useRouter } from 'vue-router';

const router = useRouter();

const features = [
    { 
        text: '프로젝트 주제 선택',
        centerText: `MindRoad 시스템은 회의 시작 단계에서
        프로젝트 주제를 명확히 설정함으로써,
        도메인 특화 데이터셋과
        맞춤형 AI 추론 환경을 자동으로 구성합니다.
        이를 통해 회의 분석의 정확도와 효율성을 극대화합니다.`,
        img: "/Data.png",
        imgClass: "bg-image-Data"
    },
    { 
        text: '실시간 회의 발화 분석',
        centerText: `본 연구는 Whisper 기반 STT와
        faster-whisper 최적화 모델을 활용하여
        참가자 발언을 실시간으로 텍스트로 변환합니다.
        발화 흐름 및 아이디어 생성 과정을
        즉각적으로 구조화함으로써,
        협업 과정의 투명성과 생산성을 동시에 확보합니다.`,
        img: "/Speech.png",
        imgClass: "bg-image-Speech"
    },
    { 
        text: '마인드맵 자동 시각화',
        centerText: `회의 발화에서 추출된 키워드와 요약 정보를
        SBERT 임베딩 기반 연관성 분석을 통해 
        실시간으로 마인드맵 노드로 변환·시각화합니다. 
        이를 통해 발언의 흐름, 의사결정 근거, 아이디어 간의
        관계가 직관적으로 탐색 가능합니다.`,
        img: "/MindMap.png",
        imgClass: "bg-image-MindMap"
    },
    { 
        text: '인공지능 기반 키워드 추천',
        centerText: `로컬 LLM에 LoRA·RAG 기법을 결합하여, 
        회의 맥락 및 도메인 특화 데이터를 반영한 키워드와
        아이디어를 실시간 추천합니다. 
        주제에 따라 관련 외부 정보가 웹 크롤링·임베딩 되어, 
        지속가능하고 확장적인 데이터셋 기반의 추천이 가능합니다.`,
        img: "/AI.png",
        imgClass: "bg-image-AI"
    }
];

const currentIndex = ref(0);
const progresses = ref(Array(features.length).fill(0));
const imageReady = ref(true);
const textReady = ref(true);

const interval = 30;
const duration = 4000;

let timer = null;

// 페이드인 애니메이션 트리거
function triggerFadeIn() {
    imageReady.value = false;
    textReady.value = false;
    
    // 약간의 지연 후 동시에 페이드인 시작
    setTimeout(() => {
        imageReady.value = true;
        textReady.value = true;
    }, 50);
}

// currentIndex 변경 감지
watch(currentIndex, () => {
    triggerFadeIn();
});

function startProgress() {
    clearInterval(timer);
    progresses.value = Array(features.length).fill(0);
    timer = setInterval(() => {
        progresses.value[currentIndex.value] += (interval / duration) * 100;
        if (progresses.value[currentIndex.value] >= 100) {
            progresses.value[currentIndex.value] = 100;
            clearInterval(timer);
            setTimeout(() => {
                if (currentIndex.value < features.length - 1) {
                    currentIndex.value++;
                    startProgress();
                }
            }, 2000); // 2초 멈춤
        }
    }, interval);
}

function goTo(idx) {
    clearInterval(timer);
    currentIndex.value = idx;
    progresses.value = Array(features.length).fill(0);
    startProgress();
}

// === 페이지 이동 함수 ===
function navigateToNextPage() {
    const isLoggedIn = (
        sessionStorage.getItem("isLoggedIn") === "true" &&
        sessionStorage.getItem("userEmail") !== null
    );
    if (isLoggedIn) {
        router.push("/MyMap");
    } else {
        router.push("/MainHome");
    }
}

// === 아래로 스크롤 시 페이지 이동 ===
let isScrolling = false;
let scrollTimeout;

function handleWheel(event) {
    if (isScrolling) return;

    // 아래로 스크롤 시
    if (event.deltaY > 50) {
        isScrolling = true;
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
            navigateToNextPage();
            setTimeout(() => {
                isScrolling = false;
            }, 500);
        }, 300);
    }
}

onMounted(() => {
    triggerFadeIn();
    startProgress();
    window.addEventListener("wheel", handleWheel, { passive: false });
});

onUnmounted(() => {
    clearInterval(timer);
    window.removeEventListener("wheel", handleWheel);
    clearTimeout(scrollTimeout);
});
</script>

<style scoped>
.landing-container {
    background: #111;
    width: 100vw;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    padding-bottom: 100px;
    position: relative;
    overflow: hidden;
}

/* 중앙 배경 이미지 스타일 (텍스트보다 z-index 낮게) */
.bg-image {
    position: absolute;
    pointer-events: none;
    opacity: 0;
    transition: opacity 1s ease-in-out;
}

.bg-image.fade-in {
    opacity: 0.6;
}

.bg-image-Data {
    top: 28%;
    left: 48.5%;
    transform: translate(-50%, -50%);
    min-width: 60vw;
    min-height: 60vh;
    max-width: 80vw;
    max-height: 80vh;
    object-fit: contain;
}

.bg-image-Speech {
    top: 28%;
    left: 50%;
    transform: translate(-50%, -50%);
    min-width: 60vw;
    min-height: 60vh;
    max-width: 65vw;
    max-height: 80vh;
    object-fit: contain;
}

.bg-image-MindMap {
    top: 38%;
    left: 50%;
    transform: translate(-50%, -50%);
    min-width: 55vw;
    min-height: 55vh;
    max-width: 55vw;
    max-height: 55vh;
    object-fit: contain;
}

.bg-image-MindMap.fade-in {
    opacity: 0.7;
}

.bg-image-AI {
    top: 40%;
    left: 50%;
    transform: translate(-50%, -50%);
    min-width: 60vw;
    min-height: 60vh;
    max-width: 80vw;
    max-height: 80vh;
    object-fit: contain;
}

.center-text {
    position: absolute;
    top: 35%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 1.7rem;
    font-weight: 500;
    color: #fff;
    letter-spacing: 0.05em;
    text-shadow: 0 2px 8px rgba(0,0,0,0.45);
    pointer-events: none;
    user-select: none;
    text-align: center;
    white-space: pre-line;
    width: 60vw;
    line-height: 1.5;
    padding: 0 1vw;
    opacity: 0;
    transition: opacity 1.3s ease-in-out;
}

.center-text.fade-in {
    opacity: 1;
}

.features {
    display: flex;
    width: 90vw;
    max-width: 1400px;
    justify-content: space-between;
}

.feature {
    flex: 1;
    margin: 0 10px;
    text-align: center;
    opacity: 0.5;
    transition: opacity 0.3s, transform 0.3s;
    cursor: pointer;
    color: #fff;
}

.feature.active {
    opacity: 1;
    font-weight: bold;
    transform: scale(1.08);
    color: #fff;
}

.feature-text {
    font-size: 1.1rem;
    margin-bottom: 12px;
    letter-spacing: 1px;
    color: #fff;
}

.progress-bar {
    width: 80%;
    height: 3px;
    background: #333;
    margin: 0 auto;
    border-radius: 2px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background: #fff;
    transition: width 0.2s;
}

.scroll-guide {
    width: 100vw;
    position: absolute;
    bottom: 24px;
    left: 0;
    text-align: center;
    font-size: 1.1rem;
    color: #aaa;
    letter-spacing: 0.08em;
    z-index: 10;
    user-select: none;
    opacity: 0.8;
    font-family: 'Inter', 'Pretendard', 'sans-serif';
    animation: pulse 2s infinite;
    padding-bottom: 8px;
    cursor: pointer;
    transition: opacity 0.3s ease;
}

.scroll-guide:hover {
    opacity: 1;
}

.scroll-guide .arrow {
    display: block;
    font-size: 2.2rem;
    margin-top: 8px;
    color: #aaa;
    animation: arrowBounce 1.2s infinite;
}

@keyframes pulse {
    0% { opacity: 0.8; }
    50% { opacity: 1; }
    100% { opacity: 0.8; }
}

@keyframes arrowBounce {
    0% { transform: translateY(0); }
    50% { transform: translateY(12px); }
    100% { transform: translateY(0); }
}
</style>