<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api.js";

const props = defineProps({
  branchId: { type: Number, default: null },
  events: { type: Array, default: () => [] },
});

const KEY_STORAGE = "worldbranch.llm_key";
const SETTINGS_STORAGE = "worldbranch.llm_settings";

const provider = ref({
  name: "我的模型",
  kind: "openai_compatible",
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
});
const apiKey = ref("");
const showSettings = ref(false);
const question = ref("");
const focusEventId = ref(null);
const answer = ref("");
const citations = ref([]);
const meta = ref(null);
const material = ref("");
const showMaterial = ref(false);
const busy = ref(false);
const error = ref("");

onMounted(() => {
  apiKey.value = localStorage.getItem(KEY_STORAGE) || "";
  const saved = localStorage.getItem(SETTINGS_STORAGE);
  if (saved) {
    try {
      provider.value = { ...provider.value, ...JSON.parse(saved) };
    } catch (e) {
      /* 忽略坏数据 */
    }
  }
  if (!apiKey.value) showSettings.value = true;
});

function saveSettings() {
  localStorage.setItem(KEY_STORAGE, apiKey.value);
  localStorage.setItem(SETTINGS_STORAGE, JSON.stringify(provider.value));
  showSettings.value = false;
  error.value = "";
}

async function saveProvider() {
  try {
    await api.saveProvider({
      name: provider.value.name,
      kind: provider.value.kind,
      base_url: provider.value.base_url,
      model: provider.value.model,
      is_default: true,
    });
  } catch (err) {
    error.value = `保存配置失败：${err.message}`;
  }
}

async function run() {
  if (!props.branchId || busy.value) return;
  busy.value = true;
  error.value = "";
  answer.value = "";
  citations.value = [];
  meta.value = null;
  try {
    await saveProvider();
    const result = await api.analyze(
      props.branchId,
      question.value,
      focusEventId.value,
      apiKey.value
    );
    answer.value = result.answer;
    citations.value = result.citations || [];
    meta.value = result.context;
    material.value = result.material_preview || "";
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = false;
  }
}

async function previewMaterial() {
  if (!props.branchId) return;
  try {
    const data = await api.material(props.branchId, focusEventId.value);
    material.value = data.text;
    citations.value = data.citations || [];
    showMaterial.value = true;
  } catch (err) {
    error.value = err.message;
  }
}

const RELIABILITY = {
  primary: "一手史料",
  secondary: "研究概述",
  assumption: "建模假设",
};
</script>

<template>
  <div class="ai-panel">
    <div class="ai-head">
      <h2>AI 分析</h2>
      <span class="ai-note">使用你自己的模型与 Key，本服务不保存 Key</span>
      <button class="link-btn" @click="showSettings = !showSettings">
        {{ showSettings ? "收起设置" : "模型设置" }}
      </button>
    </div>

    <div v-if="showSettings" class="settings">
      <div class="field">
        <label>接口地址</label>
        <input v-model="provider.base_url" placeholder="https://api.deepseek.com/v1" />
      </div>
      <div class="field">
        <label>模型名</label>
        <input v-model="provider.model" placeholder="deepseek-chat" />
      </div>
      <div class="field wide">
        <label>API Key（只存在你的浏览器里）</label>
        <input v-model="apiKey" type="password" placeholder="sk-..." autocomplete="off" />
      </div>
      <div class="field">
        <label>适配器</label>
        <select v-model="provider.kind">
          <option value="openai_compatible">OpenAI 兼容</option>
          <option value="mock">离线模拟（不调用模型）</option>
        </select>
      </div>
      <button class="primary" @click="saveSettings">保存到本地</button>
    </div>

    <div class="ask">
      <div class="field wide">
        <label>你的问题</label>
        <input
          v-model="question"
          placeholder="例如：河北的粮荒是如何影响到其他道的？"
          @keyup.enter="run"
        />
      </div>
      <div class="field">
        <label>可选的焦点事件</label>
        <select v-model="focusEventId">
          <option :value="null">不指定</option>
          <option v-for="e in events.slice(0, 40)" :key="e.id" :value="e.id">
            {{ e.game_date }} {{ e.title }}
          </option>
        </select>
      </div>
      <button class="primary" :disabled="busy" @click="run">
        {{ busy ? "分析中…" : "开始分析" }}
      </button>
      <button class="ghost" @click="previewMaterial">先看材料</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="answer" class="answer">
      <div class="answer-title">分析结果</div>
      <p class="answer-text">{{ answer }}</p>
      <div v-if="meta" class="meta">
        <span>材料：{{ meta.region_count }} 个道 · {{ meta.event_count }} 条事件</span>
        <span v-if="meta.focus_event">· 焦点：{{ meta.focus_event }}</span>
        <span v-if="meta.cause_chain_length">· 因果链 {{ meta.cause_chain_length }} 节</span>
        <span>· 引用资料 {{ meta.knowledge_hits }} 条</span>
      </div>
    </div>

    <div v-if="citations.length" class="citations">
      <div class="citations-title">引用资料</div>
      <div v-for="c in citations" :key="c.title" class="citation">
        <span class="c-title">{{ c.title }}</span>
        <span class="c-source">{{ c.source }}</span>
        <span class="c-tag">{{ RELIABILITY[c.reliability] || c.reliability }}</span>
      </div>
    </div>

    <div v-if="material" class="material">
      <div class="material-head">
        <span>送给模型的材料</span>
        <button class="link-btn" @click="showMaterial = !showMaterial">
          {{ showMaterial ? "收起" : "展开" }}
        </button>
      </div>
      <pre v-if="showMaterial" class="material-body">{{ material }}</pre>
    </div>
  </div>
</template>

<style scoped>
.ai-panel { padding: 16px 20px; max-width: 980px; margin: 0 auto; height: 100%; overflow: auto; }
.ai-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.ai-head h2 { font-size: 15px; margin: 0; }
.ai-note { font-size: 11px; color: #8fa1b0; }
.link-btn { background: none; border: none; color: #4aa8d8; cursor: pointer; font-size: 11px; margin-left: auto; }

.settings, .ask {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
  background: #161d24; border: 1px solid #2a3540; border-radius: 10px;
  padding: 12px; margin-bottom: 12px;
}
.field { display: flex; flex-direction: column; gap: 4px; min-width: 180px; }
.field.wide { flex: 1; min-width: 280px; }
.field label { font-size: 11px; color: #8fa1b0; }
.field input, .field select {
  background: #1d262f; color: #dfe7ee; border: 1px solid #2a3540;
  border-radius: 7px; padding: 7px 10px; font-size: 12px; outline: none;
}
.field input:focus, .field select:focus { border-color: #4aa8d8; }

.primary {
  padding: 8px 18px; border-radius: 8px; border: 1px solid #4aa8d8;
  background: rgba(74, 168, 216, 0.16); color: #4aa8d8; cursor: pointer; font-size: 12px;
}
.primary:disabled { opacity: 0.5; cursor: progress; }
.ghost {
  padding: 8px 14px; border-radius: 8px; border: 1px solid #2a3540;
  background: transparent; color: #8fa1b0; cursor: pointer; font-size: 12px;
}
.ghost:hover { color: #4aa8d8; border-color: #4aa8d8; }

.error { color: #d8614a; font-size: 12px; margin-bottom: 10px; }

.answer { background: #161d24; border: 1px solid #2a3540; border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.answer-title { font-size: 12px; color: #d8a24a; margin-bottom: 8px; }
.answer-text { margin: 0; font-size: 13px; line-height: 1.75; white-space: pre-wrap; }
.meta { margin-top: 10px; font-size: 10.5px; color: #8fa1b0; display: flex; gap: 6px; flex-wrap: wrap; }

.citations { margin-bottom: 12px; }
.citations-title { font-size: 11px; color: #8fa1b0; margin-bottom: 6px; }
.citation { display: flex; gap: 10px; font-size: 11.5px; padding: 4px 0; border-bottom: 1px dashed rgba(42,53,64,.6); }
.c-title { color: #dfe7ee; }
.c-source { color: #8fa1b0; }
.c-tag {
  margin-left: auto; font-size: 10px; padding: 1px 7px; border-radius: 5px;
  background: rgba(216,162,74,.15); color: #d8a24a;
}

.material { background: #10161c; border: 1px solid #2a3540; border-radius: 10px; padding: 10px 12px; }
.material-head { display: flex; align-items: center; font-size: 11px; color: #8fa1b0; }
.material-body {
  margin: 8px 0 0; font-size: 11px; line-height: 1.7; color: #c6d6e2;
  white-space: pre-wrap; max-height: 340px; overflow: auto;
  font-family: "Consolas", "Microsoft YaHei", monospace;
}
</style>