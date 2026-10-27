// 无子进程的 Vite 构建入口。
//
// 本机环境禁止 Node 以管道方式 spawn 子进程（EPERM），而 Vite 在 Windows 上
// 会调用 `net use` 检测网络驱动器、并用 esbuild 做若干转换，这些都会 spawn。
// 这里在加载 Vite 之前把 child_process 的几个入口替换成"立即失败"，
// 让 Vite 走它自带的降级分支（普通 realpath），其余纯 JS 的构建流程不受影响。
//
// 用法：node build.mjs

import childProcess from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function disabled(name) {
  const fn = (...args) => {
    const cb = args.find((a) => typeof a === "function");
    const err = Object.assign(new Error(`spawn disabled (${name})`), {
      code: "EPERM",
    });
    if (cb) {
      cb(err);
      return undefined;
    }
    throw err;
  };
  return fn;
}

for (const name of ["exec", "execSync", "execFile", "execFileSync", "spawn", "spawnSync", "fork"]) {
  childProcess[name] = disabled(name);
}
if (childProcess.default) {
  for (const name of ["exec", "execSync", "execFile", "execFileSync", "spawn", "spawnSync", "fork"]) {
    childProcess.default[name] = disabled(name);
  }
}

// 内置模块的 ESM 具名导入是快照，必须同步一次才让 Vite 里的 import 看到补丁
require("node:module").syncBuiltinESMExports();

const { build } = await import("vite");

await build({
  configFile: "./vite.config.js",
  configLoader: "native",
  logLevel: "info",
});

// 另外产出一个 IIFE 包，专门给 jsdom 做冒烟测试用
// （浏览器用的 ESM 包 jsdom 执行不了）。
await build({
  configFile: "./vite.config.js",
  configLoader: "native",
  logLevel: "warn",
  build: {
    outDir: "dist-smoke",
    emptyOutDir: true,
    minify: false,
    target: "esnext",
    lib: {
      entry: "./src/main.js",
      formats: ["iife"],
      name: "WorldBranchApp",
      fileName: () => "app.js",
    },
  },
});

console.log("build finished");