import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import notoKR_Regular from "./font/fontJS/NotoSansKR-Regular";  
import notoKR_Bold from "./font/fontJS/NotoSansKR-Bold";
 
export default async function meetingPDF2(data) {
  // ✅ PDF 생성
  const doc = new jsPDF();

  doc.addFileToVFS("NotoSansKR-Regular.ttf", notoKR_Regular);
  doc.addFont("NotoSansKR-Regular.ttf", "NotoSansKR", "normal");


  doc.addFileToVFS("NotoSansKR-Bold.ttf", notoKR_Bold);
  doc.addFont("NotoSansKR-Bold.ttf", "NotoSansKR", "bold");
  
  doc.setFont("NotoSansKR", "normal");

  const now = new Date();
  const dateStr = now.toLocaleDateString().replace(/\.$/, "");
  const timeStr = now.toLocaleTimeString();

  const { speakerNames, srt, minutes } = data;

  doc.setFontSize(18);
  const pageWidth = doc.internal.pageSize.getWidth();

  // ✅ 텍스트 너비 계산
  const text = "회의록";
  const textWidth = doc.getTextWidth(text);

  // ✅ 중앙 위치 계산
  const xPos = (pageWidth - textWidth) / 2;

  doc.text(text, xPos, 15);

  const tableData = [
    ["날짜", dateStr, "시간", timeStr],
    ["참여자", speakerNames.join(", "), "목적", minutes.purpose],
    ["주제", minutes.topics.join(",")],
  ];

  // ✅ 테이블 생성
  autoTable(doc, {
    startY: 25,
    head: [["", "", "", ""]],
    body: tableData,
    headStyles: { fillColor: "#1abd9c" },
    styles: { font: "NotoSansKR", fontSize: 12, overflow: "linebreak" },
    theme: "grid",
    columnStyles: {
      0: { cellWidth: "wrap" },
      1: { cellWidth: "auto" },
      2: { cellWidth: "wrap" },
      3: { cellWidth: "auto" },
    },
  });

  const srtTable = srt.map((item) => [
    item.time,
    `${item.speaker}: ${item.speech}`,
  ]);

  autoTable(doc, {
    startY: doc.lastAutoTable.finalY + 10,
    head: [
      [{ content: "대화내용 (SRT)", colSpan: 2, styles: { halign: "center" } }],
      ["Time", "Content"],
    ],
    body: srtTable,
    headStyles: {
      font: "NotoSansKR",
      fontStyle: "bold",
      lineWidth: 0.5,
      lineColor: [255, 255, 255],
    },
    styles: { font: "NotoSansKR", fontStyle: "normal", overflow: "linebreak" },
    columnStyles: {
      0: { cellWidth: 40 },
      1: { cellWidth: "auto" },
    },
    theme: "grid",
  });

  doc.addPage(); // 공간 부족 시에만 새 페이지 추가

  doc.setFontSize(15);

  autoTable(doc, {
    startY: 58,
    head: [""],
    body: [
      ["회의 목적", minutes.purpose],
      ["주요 주제", minutes.topics.join(",")],
      ["다음 할 일", minutes.next_steps.join(",")],
      ["요약", minutes.summary],
      
    ],
    headStyles: {
      font: "NotoSansKR",
      fontStyle:"bold",
      fontSize: 12,
      lineWidth: 0.5,
      lineColor: [255, 255, 255],
      fillColor: "#1abd9c",
    },
    bodyStyles: { font: "NotoSansKR", fontSize: 12 },
    styles: {
      font: "NotoSansKR",
      fontStyle: "normal",
      halign: "left",
      valign: "top",
      overflow: "linebreak",
    },
    theme: "grid",
    columnStyles: {
      0: { fontStyle: "normal", cellWidth: 40 },
      1: { cellWidth: "auto" },
    },
  });

  // 🔑 키워드
  // autoTable(doc, {
  //   startY: doc.lastAutoTable.finalY + 16,
  //   head: [[{ content: "주요 키워드", styles: { halign: "center" } }]],
  //   body: minutes.keywords.map((k) => [k]),
  //   headStyles: { font: "NotoSansKR", fontStyle: "bold",fillColor: "#1abd9c" },
  //   theme: "striped",
  //   styles: { font: "NotoSansKR", fontStyle: "normal", halign: "left" },
  // });

  return doc;
}
