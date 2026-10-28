import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";
import { installSound } from "./sound.js";

createApp(App).mount("#app");

// 全局挂一次即可：所有按钮与可点元素的点击都有反馈音
installSound();