"""打包可分发的发布产物，并验证解压后能一键启动。

    python tools/package.py              # 只打包
    python tools/package.py --verify     # 解到干净目录，按步骤实跑一遍
    python tools/package.py --oneclick   # 解到干净目录，用包里的 start 脚本启动

产物：dist-package/worldbranch-<日期>.tar.gz
包含：backend、frontend/dist、tools、deploy、start.bat / start.sh，
      不含 instance、.env、__pycache__、测试缓存。

--oneclick 走的是使用者真实路径：
  解包 → 执行包内 tools/bootstrap.py → 建库播种 → 起服务 → 接口自检
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist-package"
CHECK_DIR = ROOT / ".tmp" / "pkgcheck"

#: 不打进包里的东西
EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    "instance",
    "node_modules",
    ".tmp",
    "dist-package",
    "dist-smoke",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log"}
EXCLUDE_FILES = {".env"}


def copy_tree(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if item.is_dir():
            continue
        if item.name in EXCLUDE_FILES or item.suffix in EXCLUDE_SUFFIX:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def build() -> Path:
    stamp = dt.date.today().isoformat()
    stage = OUT_DIR / f"worldbranch-{stamp}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    copy_tree(ROOT / "backend", stage / "backend")
    # 前端只带产物：使用者不需要装 Node
    shutil.copytree(ROOT / "frontend" / "dist", stage / "frontend" / "dist")
    copy_tree(ROOT / "deploy", stage / "deploy")
    # 一键启动需要的东西
    copy_tree(ROOT / "tools", stage / "tools")
    for name in ("start.bat", "start.sh"):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, stage / name)

    (stage / "README-部署.txt").write_text(
        "WorldBranch 发布包\n"
        "==================\n\n"
        "【最简单的方式】\n"
        "  Windows：双击 start.bat\n"
        "  Linux/macOS：./start.sh\n"
        "  脚本会自动建虚拟环境、装依赖、建库、播种、起服务并打开浏览器。\n"
        "  数据存在 backend/instance/worldbranch.db（SQLite），不需要装数据库。\n\n"
        "【手动部署到服务器】\n"
        "1. 建虚拟环境并装依赖：\n"
        "   python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt\n\n"
        "2. 配置数据库（backend/.env）：\n"
        "   WORLDBRANCH_DATABASE_URL=mysql+pymysql://用户:密码@127.0.0.1:3306/库?charset=utf8mb4\n\n"
        "3. 建表与播种：\n"
        "   cd backend && FLASK_APP=run.py ../.venv/bin/python -m flask init-db\n"
        "   cd backend && FLASK_APP=run.py ../.venv/bin/python -m flask seed\n\n"
        "4. 起服务：\n"
        "   cd backend && HOST=127.0.0.1 PORT=5210 python serve.py\n\n"
        "5. 自检：\n"
        "   python tools/check_api.py http://127.0.0.1:5210\n\n"
        "详细说明见 deploy/ 与 docs/部署说明.md。\n",
        encoding="utf-8",
    )

    tar_path = OUT_DIR / f"worldbranch-{stamp}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)

    size_mb = tar_path.stat().st_size / 1024 / 1024
    files = sum(1 for _ in stage.rglob("*") if _.is_file())
    print(f"已打包 {tar_path}（{size_mb:.1f} MB，{files} 个文件）")
    return tar_path


def rmtree_retry(path: Path, attempts: int = 5) -> None:
    """Windows 上子进程退出后目录可能还被占用一会儿，重试几次。"""
    for i in range(attempts):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(0.6)


def kill_listener(port: int) -> None:
    """把监听该端口的进程结束掉。

    Windows 上 terminate 一个父进程不会连带它的子进程，
    bootstrap 拉起的 serve.py 会继续占着目录与端口。
    """
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=15
            ).stdout
            pids = set()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper().startswith("TCP"):
                    if parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                        pids.add(parts[4])
            for pid in pids:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=15
                )
        else:
            subprocess.run(
                ["bash", "-c", f"lsof -ti:{port} | xargs -r kill -9"],
                capture_output=True,
                timeout=15,
            )
    except (OSError, subprocess.SubprocessError):
        pass


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


def _verify_python() -> str:
    """验证时用项目虚拟环境（如果存在）：它才是使用者实际会用的解释器。"""
    for rel in ("Scripts/python.exe", "bin/python"):
        candidate = ROOT / ".venv" / rel
        if candidate.exists():
            return str(candidate)
    return sys.executable


def verify(tar_path: Path, port: int = 5320) -> int:
    if CHECK_DIR.exists():
        shutil.rmtree(CHECK_DIR)
    CHECK_DIR.mkdir(parents=True)

    with tarfile.open(tar_path) as tar:
        tar.extractall(CHECK_DIR, filter="data")
    roots = [p for p in CHECK_DIR.iterdir() if p.is_dir()]
    if not roots:
        print("✗ 解包后没有目录")
        return 1
    pkg = roots[0]
    print(f"解包到 {pkg}")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["WORLDBRANCH_DATABASE_URL"] = f"sqlite:///{(CHECK_DIR / 'pkg.db').as_posix()}"
    env["FLASK_APP"] = "run.py"
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    env["THREADS"] = "4"

    backend = pkg / "backend"
    py = _verify_python()
    print(f"    使用解释器：{py}")
    for cmd in (["-m", "flask", "init-db"], ["-m", "flask", "seed"]):
        print(f"    $ {' '.join(cmd)}")
        if subprocess.run([py, *cmd], cwd=backend, env=env).returncode != 0:
            print(f"✗ {cmd[-1]} 失败")
            return 1

    log = CHECK_DIR / "serve.log"
    proc = subprocess.Popen(
        [py, "serve.py"],
        cwd=backend,
        env=env,
        stdout=log.open("wb"),
        stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        if not wait_health(f"{url}/api/health"):
            print(log.read_text(encoding="utf-8", errors="replace")[-1500:])
            print("✗ 发布包里的服务没起来")
            return 1
        print("    服务已就绪，跑部署自检")
        code = subprocess.run(
            [py, str(ROOT / "tools" / "check_api.py"), url],
            cwd=ROOT,
            env=env,
        ).returncode
        if code != 0:
            print("✗ 部署自检未通过")
            return 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("✓ 发布包自包含，可独立运行")
    return 0


def verify_oneclick(tar_path: Path, port: int = 5330) -> int:
    """解包后直接跑包里的 tools/bootstrap.py，验证「下载解压就能用」。

    用 --python 指向已有环境，避免在验证时又去联网装一遍依赖；
    开库、建表、播种、起服务、等健康检查这些真实路径全都走一遍。
    """
    # 每次用独立目录：上一次的残留（尤其被进程占住的）不会影响这一次
    target = ROOT / ".tmp" / f"oneclick-{os.getpid()}"
    rmtree_retry(target)
    target.mkdir(parents=True)
    with tarfile.open(tar_path) as tar:
        tar.extractall(target, filter="data")
    roots = [p for p in target.iterdir() if p.is_dir()]
    if not roots:
        print("✗ 解包后没有目录")
        return 1
    pkg = roots[0]
    print(f"解包到 {pkg}")

    py = _verify_python()
    print(f"    用一键脚本启动（解释器 {py}）")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    log = target / "oneclick.log"
    proc = subprocess.Popen(
        [
            py,
            str(pkg / "tools" / "bootstrap.py"),
            "--no-browser",
            "--port",
            str(port),
            "--python",
            py,
        ],
        cwd=pkg,
        env=env,
        stdout=log.open("wb"),
        stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        if not wait_health(f"{url}/api/health"):
            print(log.read_text(encoding="utf-8", errors="replace")[-2000:])
            print("✗ 一键脚本没能把服务带起来")
            return 1
        print("    一键脚本已把服务带起来，跑部署自检")
        code = subprocess.run(
            [py, str(ROOT / "tools" / "check_api.py"), url], cwd=ROOT, env=env
        ).returncode
        if code != 0:
            print("✗ 部署自检未通过")
            return 1
    finally:
        # bootstrap 会拉起 serve.py 子进程，这里按端口兜底清理，
        # 否则残留进程会占着 .tmp/oneclick 目录，下一次验证就删不掉。
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        kill_listener(port)
        time.sleep(0.5)

    print("✓ 解压后一键启动可用")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="打包后在干净目录实跑一遍")
    parser.add_argument(
        "--oneclick",
        action="store_true",
        help="用包里自带的一键脚本启动（最接近使用者的真实路径）",
    )
    parser.add_argument("--port", type=int, default=5320)
    args = parser.parse_args()

    tar_path = build()
    if args.oneclick:
        print("\n==> 用发布包里的一键脚本启动")
        return verify_oneclick(tar_path, args.port)
    if args.verify:
        print("\n==> 在干净目录验证发布包")
        return verify(tar_path, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())