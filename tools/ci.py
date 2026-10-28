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

    # ---------- 2. 史料数据完整性 ----------
    say("史料数据完整性")
    code = run([sys.executable, "tools/check_tang_data.py"], ROOT, env)
    if code != 0:
        return fail("数据校验")

    # ---------- 3. 建库 + 播种 ----------
    say("建库与播种")
    for cmd in (["-m", "flask", "init-db"], ["-m", "flask", "seed"]):
        code = run([sys.executable, *cmd], BACKEND, env)
        if code != 0:
            return fail(cmd[-1])

    if args.skip_frontend:
        say("跳过前端（--skip-frontend）")
        print("\n✓ 后端部分通过", flush=True)
        return 0

    # ---------- 4. 前端构建 ----------
    say("前端构建")
    code = run([node_bin(), "build.mjs"], FRONTEND, env)
    if code != 0:
        return fail("前端构建")

    # ---------- 5. 起服务 + 渲染冒烟 ----------
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

        say("渲染冒烟")
        code = run([node_bin(), "smoke.mjs", url], FRONTEND, env)
        if code != 0:
            return fail("渲染冒烟")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()

    print("\n✓ 全部通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())