import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import notoKR_Regular from "./font/fontJS/NotoSansKR-Regular";
import notoKR_Bold from "./font/fontJS/NotoSansKR-Bold";

export default async function meetingPDF02(data) {
  const doc = new jsPDF();
  const themeColor = [26, 189, 156]; // 메인 테마 색 (#1abd9c)

  // ✅ 폰트 등록
  doc.addFileToVFS("NotoSansKR-Regular.ttf", notoKR_Regular);
  doc.addFont("NotoSansKR-Regular.ttf", "NotoSansKR", "normal");
  doc.addFileToVFS("NotoSansKR-Bold.ttf", notoKR_Bold);
  doc.addFont("NotoSansKR-Bold.ttf", "NotoSansKR", "bold");

  doc.setFont("NotoSansKR", "normal");

  const now = new Date();
  const dateStr = now.toLocaleDateString();
  const timeStr = now.toLocaleTimeString();

  const { speakerNames, srt, minutes } = data;
  const pageWidth = doc.internal.pageSize.getWidth();

  // ✅ 상단 타이틀 (헤더 느낌)
  doc.setFillColor(...themeColor);
  doc.rect(0, 0, pageWidth, 25, "F");
  doc.setTextColor(255, 255, 255);
  doc.setFont("NotoSansKR", "bold");
  doc.setFontSize(20);
  doc.text("📋 회의록 보고서", pageWidth / 2, 17, { align: "center" });

  // ✅ 기본 텍스트 색상 복구
  doc.setTextColor(0, 0, 0);
  doc.setFont("NotoSansKR", "normal");

  // 📌 회의 개요 테이블
  autoTable(doc, {
    startY: 35,
    body: [
      ["📅 날짜", dateStr, "⏰ 시간", timeStr],
      ["👥 참여자", speakerNames.join(", "), "🎯 목적", minutes.purpose],
      ["📌 주요 주제", minutes.topics.join(", ")],
    ],
    styles: {
      font: "NotoSansKR",
      fontSize: 12,
      halign: "left",
      lineColor: themeColor,
      lineWidth: 0.3,
      cellPadding: 4,
    },
    columnStyles: {
      0: { fontStyle: "bold", fillColor: [245, 245, 245], cellWidth: 35 },
      2: { fontStyle: "bold", fillColor: [245, 245, 245], cellWidth: 35 },
    },
    theme: "grid",
  });

  // 📜 회의 내용 섹션 제목
  doc.setFont("NotoSansKR", "bold");
  doc.setFontSize(16);
  doc.setTextColor(...themeColor);
  doc.text("📝 회의 내용 요약", 14, doc.lastAutoTable.finalY + 20);
  doc.setTextColor(0, 0, 0);

  autoTable(doc, {
    startY: doc.lastAutoTable.finalY + 28,
    body: [
      ["회의 목적", minutes.purpose],
      ["주요 주제", minutes.topics.join(", ")],
      ["다음 할 일", minutes.next_steps.join(", ")],
      ["요약", minutes.summary],
    ],
    styles: {
      font: "NotoSansKR",
      fontSize: 12,
      cellPadding: 5,
      overflow: "linebreak",
      lineColor: themeColor,
      lineWidth: 0.3,
    },
    columnStyles: {
      0: { fontStyle: "bold", fillColor: [245, 245, 245], cellWidth: 35 },
    },
    theme: "grid",
    alternateRowStyles: { fillColor: [250, 250, 250] },
  });

  // 📄 새 페이지 추가
  doc.addPage();

  // 🗣️ 대화 내용 섹션 제목
  doc.setFontSize(16);
  doc.setFont("NotoSansKR", "bold");
  doc.setTextColor(...themeColor);
  doc.text("💬 회의 대화 로그 (SRT)", 14, 20);
  doc.setTextColor(0, 0, 0);
  doc.setFont("NotoSansKR", "normal");

  const srtTable = srt.map((item) => [
    item.time,
    `${item.speaker}: ${item.speech}`,
  ]);

  autoTable(doc, {
    startY: 30,
    head: [["🕒 시간", "💭 내용"]],
    body: srtTable,
    styles: {
      font: "NotoSansKR",
      fontSize: 11,
      overflow: "linebreak",
      cellPadding: 4,
      lineColor: themeColor,
      lineWidth: 0.2,
    },
    headStyles: {
      fillColor: themeColor,
      textColor: 255,
      fontStyle: "bold",
    },
    columnStyles: {
      0: { cellWidth: 35 },
      1: { cellWidth: "auto" },
    },
    theme: "grid",
    alternateRowStyles: { fillColor: [250, 250, 250] },
  });

  // 📍 푸터 (페이지 번호)
  const pageCount = doc.internal.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(10);
    doc.setTextColor(150);
    doc.text(
      `Page ${i} of ${pageCount}`,
      pageWidth - 20,
      doc.internal.pageSize.getHeight() - 10
    );
  }

  return doc;
}
