// 按键音效：全部用 WebAudio 现场合成，不带任何音频文件。
//
// 为什么合成而不是用 mp3/ogg：
//   1. 发布包体积小（0 字节音频），首次点击不会有加载延迟；
//   2. 音高、时长可以按操作类型微调，听起来是一套东西；
//   3. 不需要处理多格式兼容。
//
// 调性：木质、短促，像棋子落在盘上。不是"叮咚"的电子音。
//
// 浏览器策略：AudioContext 必须由用户手势创建/resume，
// 所以这里在第一次 pointerdown/keydown 时才初始化。

const STORAGE_KEY = "wb:muted";

let ctx = null;
let master = null;
let muted = false;

try {
  muted = window.localStorage.getItem(STORAGE_KEY) === "1";
} catch {
  muted = false;
}

function ensureContext() {
  if (ctx) return ctx;
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (!Ctor) return null; // jsdom / 老浏览器：静默降级
  ctx = new Ctor();
  master = ctx.createGain();
  master.gain.value = 0.18; // 整体音量：能听见但不吵
  master.connect(ctx.destination);
  return ctx;
}

/** 木质感的一击：短促的正弦 + 快速衰减 + 一点噪声。 */
function knock(freq, duration = 0.06, gain = 1, decay = 26) {
  const c = ensureContext();
  if (!c || muted) return;

  const now = c.currentTime;
  const osc = c.createOscillator();
  const env = c.createGain();

  osc.type = "sine";
  osc.frequency.setValueAtTime(freq, now);
  // 轻微下滑，像敲击后的余震
  osc.frequency.exponentialRampToValueAtTime(freq * 0.82, now + duration);

  env.gain.setValueAtTime(0.0001, now);
  env.gain.exponentialRampToValueAtTime(gain, now + 0.004);
  env.gain.exponentialRampToValueAtTime(0.0001, now + duration);

  osc.connect(env);
  env.connect(master);
  osc.start(now);
  osc.stop(now + duration + 0.02);

  // 一小段高频噪声，给出"木质"的瞬态
  const noiseLen = Math.floor(c.sampleRate * 0.012);
  if (noiseLen > 0) {
    const buffer = c.createBuffer(1, noiseLen, c.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < noiseLen; i += 1) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / noiseLen) ** decay;
    }
    const src = c.createBufferSource();
    const ng = c.createGain();
    ng.gain.value = 0.12 * gain;
    src.buffer = buffer;
    src.connect(ng);
    ng.connect(master);
    src.start(now);
  }
}

const SOUNDS = {
  // 普通按钮：低而轻
  tap: () => knock(420, 0.05, 0.5),
  // 推进时间：更低沉，像更重的落子
  advance: () => knock(220, 0.09, 0.9, 20),
  // 决断：清脆一点，表示"一锤定音"
  decide: () => {
    knock(660, 0.07, 0.8, 30);
    setTimeout(() => knock(880, 0.06, 0.5, 30), 55);
  },
  // 打开面板：轻微
  open: () => knock(520, 0.04, 0.35),
  // 出错：低且闷
  error: () => knock(150, 0.12, 0.7, 16),
};

/** 播放一个音效。未知名字按 tap 处理。 */
export function play(name = "tap") {
  if (muted) return;
  const fn = SOUNDS[name] || SOUNDS.tap;
  try {
    fn();
  } catch {
    // 音频不可用时不该影响界面
  }
}

export function isMuted() {
  return muted;
}

export function setMuted(value) {
  muted = Boolean(value);
  try {
    window.localStorage.setItem(STORAGE_KEY, muted ? "1" : "0");
  } catch {
    /* 隐私模式下写不进去也没关系 */
  }
  if (muted && ctx && ctx.state === "running") {
    ctx.suspend().catch(() => {});
  } else if (!muted && ctx && ctx.state === "suspended") {
    ctx.resume().catch(() => {});
  }
}

export function toggleMuted() {
  setMuted(!muted);
  return muted;
}

/** 按元素的语义推断该用哪个音。 */
function soundFor(el) {
  if (!el) return "tap";
  if (el.closest(".d-option")) return "decide";
  if (el.closest(".advance")) return "advance";
  if (el.closest(".drawer-toggle")) return "open";
  if (el.closest(".tab-strip button")) return "tap";
  return "tap";
}

/**
 * 全局挂载：任何按钮/可点元素的点击与键盘激活都会发声。
 * 用捕获阶段，避免被组件里的 stopPropagation 漏掉。
 */
export function installSound() {
  // 第一次交互时解锁音频
  const unlock = () => {
    const c = ensureContext();
    if (c && c.state === "suspended") c.resume().catch(() => {});
  };
  window.addEventListener("pointerdown", unlock, { once: true, capture: true });
  window.addEventListener("keydown", unlock, { once: true, capture: true });

  window.addEventListener(
    "click",
    (event) => {
      const el = event.target instanceof Element ? event.target : null;
      if (!el) return;
      const clickable = el.closest(
        "button, [role='button'], .d-option, .region-hit, .advance"
      );
      if (!clickable) return;
      play(soundFor(clickable));
    },
    true
  );

  // 键盘激活（Enter / Space）也算一次按键交互
  window.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const el = event.target instanceof Element ? event.target : null;
      if (!el) return;
      if (!el.closest("button, [role='button'], .d-option")) return;
      play(soundFor(el));
    },
    true
  );
}