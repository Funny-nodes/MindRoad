const axios = require("axios");

// Colab 서버의 public URL을 직접 하드코딩 (URL 반고정)
const NGROK_URL = "https://mind-road.loca.lt";

/**
 * 특정 부모 노드(주제)와 클릭한 노드를 기반으로 하위 노드 추천 (Colab API 사용)
 * @param {string} rootTopic - 프로젝트의 주제 (루트 노드의 내용)
 * @param {string} selectedNode - 사용자가 클릭한 노드
 * @param {array} relatedNodes - 기존 노드 목록
 * @returns {Promise<string[]>} - AI가 추천하는 아이디어 목록
 */
async function getMindmapSuggestions(
  rootTopic,
  selectedNode,
  parentNode,
  relatedNodes,
  category = " " // 프론트에서 전달된 카테고리
) {
  try {
    // 코랩 ngrok API로 POST 요청
    const response = await axios.post(
      `${NGROK_URL}/mindmap`,
      {
        keyword: selectedNode, // 코랩 API는 'keyword' 파라미터 사용
        category: category,
        // 필요시 rootTopic, parentNode, relatedNodes도 추가 가능 (코랩 코드에 맞게 맞추세요)
      }
    );
    // 코랩 API 응답은 { keywords: [...] }
    return response.data.keywords || [];
  } catch (error) {
    console.error("Colab API 요청 실패:", error?.response?.data || error.message);
    return [];
  }
}

module.exports = { getMindmapSuggestions };