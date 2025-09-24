// utils/colorUtils.js
import * as go from "gojs";

const BRANCH_COLORS = ["#7ED0D6", "#5B7FE5", "#2CAAE1", "#6B5FBD"];

// hex 색상을 어둡게 만드는 함수
export function darkenColor(hex, percent = 100) {
  if (!hex) return "#000000";
  let num = parseInt(hex.slice(1), 16);
  let r = (num >> 16) & 0xff;
  let g = (num >> 8) & 0xff;
  let b = num & 0xff;

  r = Math.max(0, r - (r * percent) / 100);
  g = Math.max(0, g - (g * percent) / 100);
  b = Math.max(0, b - (b * percent) / 100);

  return (
    "#" +
    ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1).toUpperCase()
  );
}

// 브랜치 색상을 적용하는 메인 함수
export function applyBranchColors(diagram) {
  const m = diagram.model;
  const nodes = m.nodeDataArray;
  const root = nodes.find((n) => n.parent === 0);
  if (!root) return;

  diagram.startTransaction("apply branch colors");

  // 루트 depth 0
  m.setDataProperty(root, "depth", 0);

  // 1레벨: 색 배정 + depth 1
  const firstChildren = nodes.filter((n) => n.parent === root.key);
  firstChildren.forEach((n, i) => {
    m.setDataProperty(
      n,
      "branchColor",
      BRANCH_COLORS[i % BRANCH_COLORS.length]
    );
    m.setDataProperty(n, "depth", 1);
    paint(n.key, n.branchColor, 1);
  });

  // 하위: 부모색 상속 + depth 누적
  function paint(parentKey, color, depth) {
    nodes
      .filter((n) => n.parent === parentKey)
      .forEach((ch) => {
        m.setDataProperty(ch, "branchColor", color);
        m.setDataProperty(ch, "depth", depth + 1);
        paint(ch.key, color, depth + 1);
      });
  }

  // 링크에도 색상 설정
  diagram.links.each((link) => {
    const toNode = link.toNode;
    if (toNode && toNode.data.branchColor) {
      m.setDataProperty(link.data, "branchColor", toNode.data.branchColor);
    }
    if (toNode && toNode.data.isSuggested) {
      m.setDataProperty(link.data, "isSuggested", true);
    }
  });

  diagram.commitTransaction("apply branch colors");
  diagram.updateAllTargetBindings();
}
