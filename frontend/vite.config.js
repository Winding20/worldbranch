import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath } from "node:url";

// 构建产物交给 Flask 在 /app/ 下托管；旧的静态页面保留在 / 作为回退。
//
// 注意：本机环境禁止 Node 以管道方式 spawn 子进程，而 Vite 内部的 esbuild
// 转换（define 替换）会 spawn 服务进程。因此把 vue 指向预构建的浏览器 ESM
// 版本——它不含 process.env / __DEV__ 占位符，可以跳过这一步转换。
const vueBrowserBuild = fileURLToPath(
  new URL("./node_modules/vue/dist/vue.esm-browser.prod.js", import.meta.url)
);

export default defineConfig({
  plugins: [vue()],
  base: "/app/",
  resolve: {
    alias: [{ find: /^vue$/, replacement: vueBrowserBuild }],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    minify: false,
    target: "esnext",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5210",
    },
  },
});