"""一键启动：装依赖 → 建库播种 → 起服务 → 打开浏览器。

使用者双击 start.bat（Windows）或 ./start.sh（Linux/macOS）即可，
不需要预先装数据库、也不需要改任何配置文件。

    python tools/bootstrap.py            # 默认 5210 端口，自动开浏览器
    python tools/bootstrap.py --port 8080 --no-browser
    python tools/bootstrap.py --reset    # 删掉本地库重建（会丢进度）

做的事：
  1. 没有 .venv 就建一个，并装好 backend/requirements.txt
  2. 没有数据库就建表并播种（含知识库）
  3. 起 serve.py（生产模式），等健康检查通过
  4. 打开浏览器；关闭窗口或 Ctrl+C 即停止
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
VENV = ROOT / ".venv"
DB = BACKEND / "instance" / "worldbranch.db"


def say(msg: str) -> None:
    print(msg, flush=True)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


MIN_VERSION = (3, 10)


def _version_of(exe: list[str]) -> tuple[int, int] | None:
    """问一下这个解释器是几版；跑不起来就返回 None。"""
    try:
        out = subprocess.run(
            [*exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        major, minor = out.stdout.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def find_interpreter() -> list[str] | None:
    """找一个够新的 Python。

    机器上常见的坑：PATH 里的 python 是很旧的 3.8，而 py 启动器上装着 3.12。
    所以这里按顺序试，挑第一个 >= 3.10 的，而不是盲信 `python`。
    """
    candidates: list[list[str]] = []
    for name in ("py",):
        if shutil.which(name):
            for ver in ("-3.13", "-3.12", "-3.11", "-3.10"):
                candidates.append([name, ver])
    for name in ("python3", "python"):
        if shutil.which(name):
            candidates.append([name])
    candidates.append([sys.executable])

    seen: set[str] = set()
    for exe in candidates:
        key = " ".join(exe)
        if key in seen:
            continue
        seen.add(key)
        ver = _version_of(exe)
        if ver and ver >= MIN_VERSION:
            say(f"· 使用 Python {ver[0]}.{ver[1]}（{key}）")
            return exe
    return None


def ensure_python_version() -> bool:
    if sys.version_info < MIN_VERSION:
        say(f"当前 Python 是 {sys.version.split()[0]}，需要 3.10 或更高版本。")
        say("请安装新版 Python（https://www.python.org/downloads/），注意勾选 Add to PATH。")
        return False
    return True


def ensure_venv() -> Path | None:
    """建虚拟环境并装依赖。已就绪则直接返回解释器路径。"""
    py = venv_python()
    if py.exists():
        probe = subprocess.run(
            [str(py), "-c", "import flask, sqlalchemy, waitress"],
            capture_output=True,
        )
        if probe.returncode == 0:
            return py
        say("· 虚拟环境存在但依赖不全，补装一次")

    if not py.exists():
        base = find_interpreter()
        if base is None:
            say("✗ 没找到 3.10 以上的 Python，无法创建运行环境。")
            say("  请安装新版 Python（https://www.python.org/downloads/），")
            say("  安装时勾选 Add Python to PATH，然后重新运行本脚本。")
            return None
        say("· 首次运行：创建虚拟环境（约十几秒）")
        code = subprocess.run([*base, "-m", "venv", str(VENV)]).returncode
        if code != 0 or not py.exists():
            say("✗ 创建虚拟环境失败。请确认已安装完整的 Python（带 venv 模块）。")
            return None

    say("· 安装依赖（首次需要下载，之后会很快）")
    code = subprocess.run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            "-r",
            str(BACKEND / "requirements.txt"),
        ]
    ).returncode
    if code != 0:
        say("✗ 依赖安装失败。若在公司网络下，可能需要配置 pip 镜像。")
        return None
    return py


def ensure_data(py: Path) -> bool:
    """没有库就建表并播种。已有库则原样保留。"""
    env = {**os.environ, "FLASK_APP": "run.py", "PYTHONIOENCODING": "utf-8"}
    if not DB.exists():
        say("· 首次运行：创建数据库并写入内置世界（几秒钟）")
        for cmd in (["-m", "flask", "init-db"], ["-m", "flask", "seed"]):
            if subprocess.run([str(py), *cmd], cwd=BACKEND, env=env).returncode != 0:
                say("✗ 初始化数据失败")
                return False
    return True


def pick_port(preferred: int) -> int:
    """端口被占用时顺延，避免「怎么打不开」。"""
    for candidate in range(preferred, preferred + 20):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", candidate)) != 0:
                return candidate
    return preferred


def wait_health(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def reset_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB) + suffix)
        if path.exists():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5210)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reset", action="store_true", help="删除本地数据库后重建")
    parser.add_argument(
        "--python",
        default="",
        help="指定已有的 Python 环境（跳过建虚拟环境与装依赖），主要用于自动化验证",
    )
    args = parser.parse_args()

    say("=" * 56)
    say(" WorldBranch · 安史之乱模拟器")
    say("=" * 56)

    # 已有可用虚拟环境时，启动器是几版并不重要
    if not venv_python().exists() and not ensure_python_version():
        return 1

    if args.reset:
        say("· 按要求清空本地数据库")
        reset_db()

    if args.python:
        py = Path(args.python)
        if not py.exists():
            say(f"✗ 指定的解释器不存在：{py}")
            return 1
        say(f"· 使用指定环境：{py}")
    else:
        py = ensure_venv()
        if py is None:
            return 1

    if not ensure_data(py):
        return 1

    port = pick_port(args.port)
    if port != args.port:
        say(f"· {args.port} 端口被占用，改用 {port}")

    env = {
        **os.environ,
        "HOST": args.host,
        "PORT": str(port),
        "THREADS": "8",
        "PYTHONIOENCODING": "utf-8",
        "WORLDBRANCH_DEBUG": "0",
    }
    url = f"http://127.0.0.1:{port}/"
    say(f"· 启动服务：{url}")
    proc = subprocess.Popen([str(py), "serve.py"], cwd=BACKEND, env=env)

    try:
        if not wait_health(f"http://127.0.0.1:{port}/api/health"):
            say("✗ 服务没能在 60 秒内就绪")
            return 1
        say("")
        say("  ✓ 服务已就绪")
        say(f"    地址：{url}")
        if not args.no_browser:
            say("    已打开浏览器；关闭这个窗口即停止服务")
            webbrowser.open(url)
        else:
            say("    按 Ctrl+C 停止服务")
        say("")
        proc.wait()
    except KeyboardInterrupt:
        say("\n· 正在停止…")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())