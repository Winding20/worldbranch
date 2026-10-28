"""WorldBranch CI：一条命令跑完全部检查。

本地与 GitHub Actions 共用这一份实现，避免两套脚本走偏。

    python tools/ci.py
    python tools/ci.py --skip-frontend
    python tools/ci.py --port 5300

检查项：
  1. 后端测试（pytest，SQLite，不碰远程库）
  2. 史料数据完整性（事件 key / 条件 / 效果引用）
  3. 建库 + 播种（独立 SQLite 文件）
  4. 前端构建（node build.mjs）
  5. 起服务 + 渲染冒烟（node smoke.mjs）+ 关服务

任何一步失败即以非 0 退出码结束。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
TMP = ROOT / ".tmp"


def say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def fail(msg: str) -> int:
    print(f"\n✗ 失败：{msg}", file=sys.stderr, flush=True)
    return 1


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> int:
    print(f"    $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env)
    return proc.returncode


def node_bin() -> str:
    """优先用 PATH 里的 node；找不到就报清楚，不静默跳过。"""
    exe = shutil.which("node")
    if exe is None:
        raise SystemExit("找不到 node，请先安装 Node.js")
    return exe


def stop(proc: subprocess.Popen) -> None:
    """收掉子进程，别留僵尸。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_health(url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5300)
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--keep-db", action="store_true", help="复用 .tmp/ci.db")
    args = parser.parse_args()

    TMP.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 独立数据库：不让 CI 碰到开发库或远程 MySQL
    ci_db = TMP / "ci.db"
    if ci_db.exists() and not args.keep_db:
        ci_db.unlink()
    env["WORLDBRANCH_DATABASE_URL"] = f"sqlite:///{ci_db.as_posix()}"
    env["WORLDBRANCH_SQL_ECHO"] = "0"
    env["FLASK_APP"] = "run.py"
    env["PORT"] = str(args.port)
    env["HOST"] = "127.0.0.1"

    # ---------- 1. 后端测试 ----------
    say("后端测试")
    code = run([sys.executable, "-m", "pytest", "-q"], BACKEND, env)
    if code != 0:
        return fail("后端测试")

    # ---------- 2. 启动脚本 ----------
    say("启动脚本检查")
    code = run([sys.executable, "tools/check_launcher.py"], ROOT, env)
    if code != 0:
        return fail("启动脚本检查")

    # ---------- 3. 史料数据完整性 ----------
    say("史料数据完整性")
    code = run([sys.executable, "tools/check_tang_data.py"], ROOT, env)
    if code != 0:
        return fail("数据校验")

    # ---------- 4. 建库 + 播种 ----------
    say("建库与播种")
    for cmd in (["-m", "flask", "init-db"], ["-m", "flask", "seed"]):
        code = run([sys.executable, *cmd], BACKEND, env)
        if code != 0:
            return fail(cmd[-1])

    if args.skip_frontend:
        say("跳过前端（--skip-frontend）")
        print("\n✓ 后端部分通过", flush=True)
        return 0

    # ---------- 5. 前端构建 ----------
    say("前端构建")
    code = run([node_bin(), "build.mjs"], FRONTEND, env)
    if code != 0:
        return fail("前端构建")

    # 产物随仓库走（使用者无需装 Node），所以必须保证它和源码同步：
    # 重新构建后若与已提交的内容有差异，说明有人改了源码却忘了提交产物。
    say("构建产物与源码同步")
    diff = subprocess.run(
        ["git", "status", "--porcelain", "--", "frontend/dist"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        print("    （跳过：不是 git 仓库）", flush=True)
    elif diff.stdout.strip():
        print(diff.stdout)
        return fail("frontend/dist 与源码不同步，请提交重新构建的产物")
    else:
        print("    一致", flush=True)

    # ---------- 6. 起服务 + 渲染冒烟 ----------
    say(f"启动服务（端口 {args.port}）")
    log = TMP / "ci-server.log"
    server = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=log.open("wb"),
        stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{args.port}"
        if not wait_health(f"{url}/api/health"):
            print(log.read_text(encoding="utf-8", errors="replace")[-2000:])
            return fail("服务未在 40 秒内就绪")
        print("    服务已就绪", flush=True)

        say("渲染冒烟（桌面）")
        code = run([node_bin(), "smoke.mjs", url], FRONTEND, env)
        if code != 0:
            return fail("渲染冒烟（桌面）")

        say("渲染冒烟（窄屏）")
        code = run([node_bin(), "smoke-mobile.mjs", url], FRONTEND, env)
        if code != 0:
            return fail("渲染冒烟（窄屏）")
    finally:
        stop(server)

    # ---------- 7. 生产入口（一键启动用的就是它） ----------
    # 部署用的是 serve.py（waitress），这里把同一条路径也跑一遍，
    # 免得"开发能跑、上生产就崩"。
    say("生产入口 serve.py")
    prod_port = args.port + 1
    prod_env = dict(env)
    prod_env["PORT"] = str(prod_port)
    prod_env["HOST"] = "127.0.0.1"
    prod_env["THREADS"] = "4"
    prod_log = TMP / "ci-serve.log"
    prod = subprocess.Popen(
        [sys.executable, "serve.py"],
        cwd=str(BACKEND),
        env=prod_env,
        stdout=prod_log.open("wb"),
        stderr=subprocess.STDOUT,
    )
    try:
        prod_url = f"http://127.0.0.1:{prod_port}"
        if not wait_health(f"{prod_url}/api/health"):
            print(prod_log.read_text(encoding="utf-8", errors="replace")[-2000:])
            return fail("serve.py 未就绪")
        print("    serve.py 已就绪", flush=True)

        say("接口自检 check_api")
        code = run(
            [sys.executable, "tools/check_api.py", prod_url], ROOT, env
        )
        if code != 0:
            return fail("接口自检")
    finally:
        stop(prod)

    # ---------- 8. 发布包 ----------
    # 打出来的包必须能在干净目录里独立跑起来，否则"能部署"只是嘴上说说。
    say("发布包自检")
    code = run(
        [
            sys.executable,
            "tools/package.py",
            "--oneclick",
            "--port",
            str(args.port + 2),
        ],
        ROOT,
        env,
    )
    if code != 0:
        return fail("发布包自检")

    print("\n✓ 全部通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())