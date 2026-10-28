// 无浏览器环境下的渲染冒烟测试。
//
// 思路：把 Vue 应用打成 IIFE 包（jsdom 不支持 ES module），
// 在 jsdom 里加载并挂载，注入一个走真实后端接口的 fetch，
// 然后断言页面里出现了地区名和事件流。
//
// 用法：node smoke.mjs [后端地址]

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.argv[2] || "http://127.0.0.1:5210";
const BUNDLE = path.join(HERE, "dist-smoke", "app.js");
const CSS = fs
  .readdirSync(path.join(HERE, "dist", "assets"))
  .filter((f) => f.endsWith(".css"))
  .map((f) => path.join(HERE, "dist", "assets", f))[0];

if (!fs.existsSync(BUNDLE)) {
  console.error("缺少 IIFE 包，请先执行 node build.mjs");
  process.exit(2);
}

const html = `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><div id="app"></div></body></html>`;

const dom = new JSDOM(html, {
  url: BASE + "/app/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;

// 让应用能真的调到后端
window.fetch = (input, init) => {
  const url = typeof input === "string" && input.startsWith("http") ? input : BASE + input;
  return fetch(url, init);
};
window.matchMedia =
  window.matchMedia ||
  (() => ({ matches: false, addListener() {}, removeListener() {} }));

if (CSS) {
  const style = window.document.createElement("style");
  style.textContent = fs.readFileSync(CSS, "utf8");
  window.document.head.appendChild(style);
}

const errors = [];
window.addEventListener("error", (e) => errors.push(e.message));
window.addEventListener("unhandledrejection", (e) => errors.push(String(e.reason)));

const code = fs.readFileSync(BUNDLE, "utf8");
window.eval(code);

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

const deadline = Date.now() + 20000;
let body = "";
while (Date.now() < deadline) {
  await wait(400);
  body = window.document.getElementById("app").innerHTML;
  // 等到地图上真的画出地区标签为止（"道界"这类图例文字不算）
  const labels = window.document.querySelectorAll("text.region-label");
  if (labels.length > 0) break;
}
// 再多等一拍，让事件流也渲染完
await wait(600);
body = window.document.getElementById("app").innerHTML;
const regionLabelsAtStart = window.document.querySelectorAll("text.region-label");

const checks = {
  "已挂载": body.length > 200,
  "出现地图 SVG": body.includes("<svg"),
  "地区标签 7 个": regionLabelsAtStart.length >= 7,
  "出现地区名": /关内道|河南道|河北道|京兆|潼关/.test(body),
  "事件流已渲染": body.includes("事件流"),
  "出现推进按钮": /1 年/.test(body) && Boolean(window.document.querySelector(".advance-group")),
  "出现开局情境": /唐廷 · 天宝十四载/.test(body),
  "出现待决事项面板": body.includes("待决事项"),
  "出现分页标签": body.includes("军事") && body.includes("人物") && body.includes("史实"),
  "顶部 HUD 有日期": Boolean(window.document.querySelector(".hud .hud-date")),
  "底部动作条有推进": /1 年/.test(body),
  "有进度条": Boolean(window.document.querySelector(".progress-track")),
  "有抽屉开关": Boolean(window.document.querySelector(".drawer-toggle")),
  "有音效开关": Boolean(window.document.querySelector(".sound-toggle")),
  "没有失效的旧版入口": !/旧版|legacy/.test(window.document.body.innerHTML),
  "无运行时错误": errors.length === 0,
};

let failed = 0;
for (const [name, ok] of Object.entries(checks)) {
  console.log(`${ok ? "✓" : "✗"} ${name}`);
  if (!ok) failed += 1;
}
// ---- 音效：开关状态可读可切，且不报错 ----
console.log("\n【音效】");
const muteBtn = window.document.querySelector(".sound-toggle");
const muteChecks = {
  "音效开关存在": Boolean(muteBtn),
  "默认是开启状态": /音效/.test(muteBtn?.textContent || ""),
};
if (muteBtn) {
  muteBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(250);
  muteChecks["点击后变静音"] = /静音/.test(muteBtn.textContent || "");
  muteChecks["静音写入本地存储"] = window.localStorage.getItem("wb:muted") === "1";
  muteBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(250);
  muteChecks["再次点击恢复"] = /音效/.test(muteBtn.textContent || "");
  muteChecks["恢复后本地存储为 0"] = window.localStorage.getItem("wb:muted") === "0";
}
for (const [n, ok] of Object.entries(muteChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

if (errors.length) {
  console.log("\n捕获到的错误：");
  errors.slice(0, 5).forEach((e) => console.log("  -", e));
}
console.log(`\n渲染内容长度：${body.length}`);

// ---- 侧栏四个分组：决断 / 军事 / 人物 / 史实 ----
async function openPanel(name) {
  const btn = [...window.document.querySelectorAll(".tab-strip button")].find(
    (b) => b.textContent.trim().startsWith(name)
  );
  if (!btn) return null;
  btn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(300);
  return window.document.querySelector(".side-panel").innerHTML;
}

// ---- 朝议：进言的人、主张、依据 ----
// 先推进时间，确保世界真的抛出一道决策（否则朝议无从谈起）
async function clickButton(text) {
  const btn = [...window.document.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === text
  );
  if (!btn) return false;
  btn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  return true;
}

console.log("\n【朝议】");
for (let i = 0; i < 5; i += 1) {
  await clickButton("1 年");
  await wait(1500);
  const cards = window.document.querySelectorAll(".decision-card");
  if (cards.length) break;
}
const decideHtml = await openPanel("决断");
const adviceChecks = {
  "决断分组能打开": decideHtml !== null,
  "出现朝议": /朝议/.test(decideHtml || ""),
  "有进言者": /李光弼|郭子仪|李泌|哥舒翰|杨国忠/.test(decideHtml || ""),
  "有主张": /主[^<]{2,}/.test(decideHtml || ""),
  "有依据": /才略/.test(decideHtml || ""),
};
for (const [n, ok] of Object.entries(adviceChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

// ---- 决策浮层：整屏只剩这一件事 ----
console.log("\n【决策浮层】");
const overlay = window.document.querySelector(".decision-overlay");
const sheet = window.document.querySelector(".decision-sheet");
const ring = window.document.querySelector(".spotlight-ring");
const dimmed = [...window.document.querySelectorAll("path")].filter(
  (p) => p.getAttribute("opacity") && Number(p.getAttribute("opacity")) < 0.5
);
const overlayChecks = {
  "推进后弹出浮层": Boolean(overlay),
  "浮层里有奏疏卡": Boolean(sheet),
  "浮层里有选项按钮": (sheet?.querySelectorAll(".d-option").length || 0) > 0,
  "浮层里有朝议": /朝议/.test(sheet?.innerHTML || ""),
  "地图聚光到事发地": Boolean(ring),
  "其余地区被压暗": dimmed.length > 0,
};
for (const [n, ok] of Object.entries(overlayChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

// 稍后再议 -> 浮层收起，但事还在抽屉里
if (sheet) {
  const later = [...sheet.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === "稍后再议"
  );
  if (later) {
    later.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await wait(400);
  }
}
const afterLater = window.document.querySelector(".decision-overlay");
const drawerAfter = window.document.querySelectorAll(".decision-card").length;
const laterChecks = {
  "稍后再议可收起浮层": afterLater === null,
  "收起后事仍在抽屉里": drawerAfter > 0,
  "收起后不再聚光": !window.document.querySelector(".spotlight-ring"),
};
for (const [n, ok] of Object.entries(laterChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

console.log("\n【军事分组】");
const warHtml = await openPanel("军事");
const warChecks = {
  "能切到军事": warHtml !== null,
  "列出各军": /潼关守军|朔方军|范阳军/.test(warHtml || ""),
  "显示主帅": /哥舒翰|郭子仪|安禄山/.test(warHtml || ""),
  "显示双方总战力": /唐军/.test(warHtml || "") && /燕军/.test(warHtml || ""),
};
for (const [n, ok] of Object.entries(warChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

console.log("\n【人物分组】");
const peopleHtml = await openPanel("人物");
const peopleChecks = {
  "能切到人物": peopleHtml !== null,
  "列出入物": /哥舒翰|李光弼|郭子仪/.test(peopleHtml || ""),
  "显示忠诚": /忠 0\./.test(peopleHtml || "") || /忠诚/.test(peopleHtml || ""),
  "显示状态": /功高|恭顺|在朝|将叛/.test(peopleHtml || ""),
};
for (const [n, ok] of Object.entries(peopleChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

console.log("\n【史实分组】");
const historyHtml = await openPanel("史实");
const histChecks = {
  "能切到史实": historyHtml !== null,
  "显示应验计数": /应验/.test(historyHtml || ""),
  "显示改道计数": /改道/.test(historyHtml || ""),
};
for (const [n, ok] of Object.entries(histChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${n}`);
  if (!ok) failed += 1;
}

// ---- 第二个视图：分支对比 ----
const tab = [...window.document.querySelectorAll(".view-tabs button")].find(
  (b) => b.textContent.trim() === "分支对比"
);
console.log("\n【分支对比视图】");
if (!tab) {
  console.log("✗ 找不到「分支对比」标签页");
  process.exit(1);
}
tab.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));

const compareDeadline = Date.now() + 15000;
let compareText = "";
while (Date.now() < compareDeadline) {
  await wait(400);
  const root = window.document.querySelector(".compare");
  if (root && root.textContent.includes("地区状态差异")) break;
}
const compareRoot = window.document.querySelector(".compare");
compareText = compareRoot ? compareRoot.textContent : "";

const compareChecks = {
  "对比页已渲染": !!compareRoot,
  "有分支选择器": window.document.querySelectorAll(".compare select").length >= 2,
  "有派生按钮": /派生/.test(compareText),
  "有差异表格或同分支提示": /地区状态差异|同一条分支/.test(compareText),
  "对比过程无运行时错误": errors.length === 0,
};

for (const [name, ok] of Object.entries(compareChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${name}`);
  if (!ok) failed += 1;
}
if (errors.length) {
  console.log("\n捕获到的错误：");
  errors.slice(0, 5).forEach((e) => console.log("  -", e));
}
// ---- 多尺度：切到世界级，应变成势力视角 ----
console.log("\n【多尺度观察】");
const simTab = [...window.document.querySelectorAll(".view-tabs button")].find(
  (b) => b.textContent.trim() === "推演"
);
if (simTab) simTab.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
await wait(700);

const scopeSelect = window.document.querySelector("#scope");
if (!scopeSelect) {
  console.log("✗ 找不到观察尺度选择器");
  process.exit(1);
}
scopeSelect.value = "world";
scopeSelect.dispatchEvent(new window.Event("change", { bubbles: true }));

const scaleDeadline = Date.now() + 12000;
let factionText = "";
while (Date.now() < scaleDeadline) {
  await wait(400);
  factionText = window.document.querySelector("#app").textContent;
  if (factionText.includes("势力概览")) break;
}
const factionLabels = window.document.querySelectorAll("text.faction-label");
const regionLabelsAfter = window.document.querySelectorAll("text.region-label");

const scaleChecks = {
  "切换到势力概览": /势力概览/.test(factionText),
  "出现势力名标签": factionLabels.length >= 2,
  "地区标签已隐藏": regionLabelsAfter.length === 0,
  "出现势力聚合数据": /存粮/.test(factionText) && /粮价/.test(factionText),
  "尺度切换无运行时错误": errors.length === 0,
};

for (const [name, ok] of Object.entries(scaleChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${name}`);
  if (!ok) failed += 1;
}
if (errors.length) {
  console.log("\n捕获到的错误：");
  errors.slice(0, 5).forEach((e) => console.log("  -", e));
}
// ---- AI 分析视图 ----
console.log("\n【AI 分析视图】");
const aiTab = [...window.document.querySelectorAll(".view-tabs button")].find(
  (b) => b.textContent.trim() === "AI 分析"
);
if (aiTab) aiTab.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));

const aiDeadline = Date.now() + 12000;
let aiText = "";
while (Date.now() < aiDeadline) {
  await wait(400);
  const root = window.document.querySelector(".ai-panel");
  aiText = root ? root.textContent : "";
  if (aiText.includes("AI 分析")) break;
}

const aiChecks = {
  "AI 面板已渲染": !!window.document.querySelector(".ai-panel"),
  "有模型设置入口": /模型设置|收起设置/.test(aiText),
  "有提问输入框": window.document.querySelectorAll(".ai-panel input").length >= 1,
  "有材料预览入口": /先看材料/.test(aiText),
  "AI 视图无运行时错误": errors.length === 0,
};

for (const [name, ok] of Object.entries(aiChecks)) {
  console.log(`${ok ? "✓" : "✗"} ${name}`);
  if (!ok) failed += 1;
}
if (errors.length) {
  console.log("\n捕获到的错误：");
  errors.slice(0, 5).forEach((e) => console.log("  -", e));
}
process.exit(failed === 0 ? 0 : 1);