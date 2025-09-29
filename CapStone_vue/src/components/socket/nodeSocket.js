import { socket } from "./socket";
import * as go from "gojs";
import { applyBranchColors } from "../utils/colorUtils";

/**
 * 특정 노드가 다른 노드의 하위 노드인지 검사하는 함수
 * @param {string} nodeId - 이동하려는 노드의 ID
 * @param {string} newParentId - 이동하려는 부모 노드의 ID
 * @param {go.Diagram} myDiagram - GoJS 다이어그램 객체
 * @returns {boolean} - 자식 노드로 이동하면 true, 그렇지 않으면 false
 */
const isDescendant = (nodeId, newParentId, myDiagram) => {
  if (!nodeId || !newParentId) return false;

  let currentNode = myDiagram.findNodeForKey(newParentId);
  while (currentNode) {
    if (currentNode.data.key === nodeId) {
      return true; // 🚨 부모 노드가 자기 자식 노드로 이동하려 하면 true 반환
    }
    currentNode = myDiagram.findNodeForKey(currentNode.data.parent);
  }
  return false;
};

/**
 * MindMap 소켓 이벤트 핸들러 등록
 */
export const registerSocketHandlers = (myDiagram, roomId, userId) => {
  if (!myDiagram) {
    console.error("❌ myDiagram 객체가 없습니다. WebSocket 이벤트 등록 실패.");
    return;
  }

  const roomIdValue = roomId.value ? roomId.value : roomId;

  if (!socket.connected) {
    socket.connect();
    console.log("🔗 소켓 연결 시도...");
  }

  socket.emit("join-room", { roomId: roomIdValue, userId });
  console.log(`🏠 방 입장 요청: Room ID: ${roomIdValue}, User ID: ${userId}`);

  socket.on("nodeAdded", (newNodes) => {
    console.log("🟢 새로운 노드 추가됨:", newNodes);

    myDiagram.startTransaction("add node");
    newNodes.forEach((newNode) => {
      myDiagram.model.addNodeData(newNode);
    });
    myDiagram.commitTransaction("add node");

    // ✅ addNode 함수와 동일한 로직 적용
    myDiagram.layoutDiagram(true);
    
    requestAnimationFrame(() => {
      applyBranchColors(myDiagram);
      myDiagram.updateAllTargetBindings();
      myDiagram.layoutDiagram(true);
      
      requestAnimationFrame(() => {
        window.dispatchEvent(new CustomEvent("mindmap-updated"));
      });
    });

    // ✅ 색상 적용 추가
    setTimeout(() => {
      applyBranchColors(myDiagram);
      myDiagram.updateAllTargetBindings();
    }, 100);

    // 마인드맵 업데이트 이벤트 발생
    window.dispatchEvent(new CustomEvent("mindmap-updated"));
  });

  socket.on("nodeUpdated", (updatedNode) => {
    console.log("✏️ 노드 수정됨:", updatedNode);

    if (!updatedNode.key || !updatedNode.name) return;

    myDiagram.startTransaction("update node");

    const node = myDiagram.model.findNodeDataForKey(updatedNode.key);
    if (node) {
      myDiagram.model.setDataProperty(node, "name", updatedNode.name);
    } else {
      console.error("⚠️ 수정할 노드를 찾을 수 없음:", updatedNode);
    }

    myDiagram.commitTransaction("update node");

    // ✅ 추가: 레이아웃 다시 계산
    myDiagram.startTransaction("Re-layout after update");
    myDiagram.layoutDiagram(true);
    myDiagram.commitTransaction("Re-layout after update");

    // 마인드맵 업데이트 이벤트 발생
    window.dispatchEvent(new CustomEvent("mindmap-updated"));
  });

  socket.on("nodeDeleted", (deletedNodeKeys) => {
    console.log("🗑️ 삭제된 노드 리스트:", deletedNodeKeys);

    if (!Array.isArray(deletedNodeKeys) || deletedNodeKeys.length === 0) {
      console.error("🚨 잘못된 삭제 요청:", deletedNodeKeys);
      return;
    }

    if (!myDiagram) return;

    myDiagram.startTransaction("delete nodes");

    const nodesToDelete = new Set(deletedNodeKeys);

    deletedNodeKeys.forEach((parentKey) => {
      myDiagram.model.nodeDataArray.forEach((node) => {
        if (node.parent === parentKey) {
          nodesToDelete.add(node.key);
        }
      });
    });

    const selectedNodeKey = myDiagram.selection.first()?.data?.key;
    let shouldResetSelection = false;

    if (selectedNodeKey && nodesToDelete.has(selectedNodeKey)) {
      shouldResetSelection = true;
    }

    nodesToDelete.forEach((nodeKey) => {
      const node = myDiagram.model.findNodeDataForKey(nodeKey);
      if (node) {
        myDiagram.model.removeNodeData(node);
      }
    });

    myDiagram.commitTransaction("delete nodes");

    if (shouldResetSelection) {
      myDiagram.clearSelection();
      window.dispatchEvent(
        new CustomEvent("node-deleted", { detail: { resetSelection: true } })
      );
    }

    console.log("✅ 클라이언트에서 삭제 완료:", [...nodesToDelete]);

    // 마인드맵 업데이트 이벤트 발생
    window.dispatchEvent(new CustomEvent("mindmap-updated"));
  });

  // ✅ 노드 이동 이벤트 (부모가 자식으로 이동하는 것을 방지)
  socket.on("nodeMoved", (updatedNode) => {
    console.log("🔄 [Vue] 노드 이동 이벤트 수신:", updatedNode);

    const nodeData = updatedNode.dataValues || updatedNode;
    const nodeId = nodeData.id;
    const newParentId = nodeData.parent_key;

    console.log(
      `🔍 [Vue] 노드 이동 처리: 노드 ID ${nodeId}, 새 부모 ID ${newParentId}`
    );

    if (!nodeId) {
      console.error("🚨 [Vue] 노드 ID 없음:", nodeData);
      return;
    }

    // 🚨 부모가 자식으로 이동하는지 검사
    if (isDescendant(nodeId, newParentId, myDiagram)) {
      console.warn(
        "🚨 이동 불가: 부모 노드가 자식 노드의 하위로 이동할 수 없음!",
        {
          nodeId,
          newParentId,
        }
      );

      // ❌ 클라이언트에 에러 메시지 전송
      socket.emit("move-node-error", {
        roomId: roomIdValue,
        message: "부모 노드는 자식 노드의 하위로 이동할 수 없습니다.",
      });

      return;
    }

    const node =
      myDiagram.findNodeForKey(nodeId) ||
      myDiagram.findNodeForKey(String(nodeId));

    if (node) {
      console.log("✅ [Vue] 노드 찾음:", node.key);

      myDiagram.startTransaction("move node");

      const parentFieldName = "parent";
      const nodeDataObj = node.data || node;

      myDiagram.model.setDataProperty(
        nodeDataObj,
        parentFieldName,
        newParentId
      );

      myDiagram.commitTransaction("move node");

      myDiagram.layout.invalidateLayout();
      myDiagram.requestUpdate();

      console.log(
        `✅ [Vue] 노드 부모 업데이트 완료: ${nodeId} → ${newParentId}`
      );

      // ✅ 노드 이동 후 색상 재적용
      setTimeout(() => {
        applyBranchColors(myDiagram);
        myDiagram.updateAllTargetBindings();
      }, 100);

      // 마인드맵 업데이트 이벤트 발생
      window.dispatchEvent(new CustomEvent("mindmap-updated"));
    } else {
      console.warn(`🚨 [Vue] 노드 찾기 실패: ${nodeId}`);
      myDiagram.nodes.each((n) => console.log(n.key));
    }
  });

  // roleChanged 이벤트 핸들러 수정
  socket.on("roleChanged", (data) => {
    console.log("👤 역할 변경 이벤트 수신:", data);

    // 커스텀 이벤트 발생 - MindMap.vue에서 처리
    window.dispatchEvent(new CustomEvent("role-changed", { detail: data }));
  });

  // memberRemoved 이벤트 핸들러 추가
  socket.on("memberRemoved", (data) => {
    console.log("👤 멤버 제거 이벤트 수신:", data);

    // 커스텀 이벤트 발생 - MindMap.vue에서 처리
    window.dispatchEvent(new CustomEvent("member-removed", { detail: data }));
  });

  console.log("✅ WebSocket 이벤트 리스너 등록 완료");
};

/**
 * WebSocket 이벤트 해제 함수 (컴포넌트 언마운트 시 호출)
 */
export const unregisterSocketHandlers = (roomId, userId) => {
  if (!roomId || !userId) {
    console.warn("🚨 unregisterSocketHandlers: roomId 또는 userId가 없음.");
    return;
  }

  const roomIdValue =
    typeof roomId === "object" && roomId.value ? roomId.value : roomId;

  socket.off("nodeAdded");
  socket.off("nodeUpdated");
  socket.off("nodeDeleted");
  socket.off("nodeMoved");
  socket.off("roleChanged"); // 역할 변경 이벤트 리스너 해제 추가
  socket.off("memberRemoved");

  if (roomIdValue) {
    socket.emit("leave-room", { roomId: roomIdValue, userId });
    console.log(`🚪 ${userId} 님이 ${roomIdValue} 방에서 나감`);
  } else {
    console.warn("⚠️ unregisterSocketHandlers: roomIdValue가 없음.");
  }
  // 소켓 연결까지 완전히 끊고 싶을 때만
  socket.disconnect();
  console.log("🔌 소켓 연결 종료됨");
};
