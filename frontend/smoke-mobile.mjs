// 窄屏（手机尺寸）挂载测试。
//
// jsdom 不做真实布局，媒体查询不生效，所以这里验证的是 **JS 层**的手机行为：
//   - 窄屏下侧栏抽屉默认收起
//   - 点「朝局」能展开，再点能收起
//   - 推进后决策浮层铺满（结构上是 .decision-overlay + .decision-sheet）
//
// 用法：node smoke-mobile.mjs [后端地址]

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

// 390x844：常见手机竖屏
const dom = new JSDOM(
  `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><div id="app"></div></body></html>`,
  {
    url: BASE + "/app/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  }
);
const { window } = dom;
// jsdom 默认 1024 宽，这里改成手机宽度，让 App 的初始判断走窄屏分支
Object.defineProperty(window, "innerWidth", { value: 390, configurable: true });
Object.defineProperty(window, "innerHeight", { value: 844, configurable: true });

window.fetch = (input, init) => {
  const url = typeof input === "string" && input.startsWith("http") ? input : BASE + input;
  return fetch(url, init);
};
window.matchMedia =
  window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));

if (CSS) {
  const style = window.document.createElement("style");
  style.textContent = fs.readFileSync(CSS, "utf8");
  window.document.head.appendChild(style);
}

const errors = [];
window.addEventListener("error", (e) => errors.push(e.message));
window.addEventListener("unhandledrejection", (e) => errors.push(String(e.reason)));

window.eval(fs.readFileSync(BUNDLE, "utf8"));

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const deadline = Date.now() + 20000;
let body = "";
while (Date.now() < deadline) {
  await wait(400);
  body = window.document.getElementById("app").innerHTML;
  if (window.document.querySelectorAll("text.region-label").length > 0) break;
}
await wait(600);

let failed = 0;
function check(name, ok) {
  console.log(`${ok ? "✓" : "✗"} ${name}`);
  if (!ok) failed += 1;
}

const drawer = window.document.querySelector(".side-panel");
const toggle = window.document.querySelector(".drawer-toggle");

console.log("【窄屏：抽屉】");
check("页面已挂载", body.length > 200);
check("存在侧栏抽屉", Boolean(drawer));
check("窄屏下默认收起", drawer !== null && !drawer.classList.contains("open"));
check("有抽屉开关", Boolean(toggle));

if (toggle) {
  toggle.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(300);
  check("点击后展开", drawer.classList.contains("open"));
  toggle.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(300);
  check("再次点击收起", !drawer.classList.contains("open"));
}

console.log("\n【窄屏：决策浮层】");
const primary = window.document.querySelector(".advance-group .advance.primary");
check("有主推进按钮", Boolean(primary));
if (primary) {
  primary.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(1800);
}
const sheet = window.document.querySelector(".decision-overlay .decision-sheet");
check("推进后出现全屏决策", Boolean(sheet));
check(
  "决策里有可点的选项",
  (sheet?.querySelectorAll(".d-option").length || 0) > 0
);
// 手机上网浮层是不透明整屏，聚光被盖住是刻意的；这里只确认它仍被算出来
check(
  "聚光点仍已算出",
  Boolean(window.document.querySelector(".spotlight-ring"))
);

console.log("\n【窄屏：无报错】");
check("无运行时错误", errors.length === 0);
if (errors.length) {
  errors.slice(0, 5).forEach((e) => console.log("  -", e));
}

console.log(failed === 0 ? "\n✓ 窄屏检查全部通过" : `\n✗ ${failed} 项失败`);
process.exit(failed === 0 ? 0 : 1);