"""生产模式入口：用 waitress 托管（Windows / Linux 通用）。

开发时用 run.py（Flask 自带服务器，带热重载）；
对外提供服务时用这个：

    python serve.py
    $env:HOST="127.0.0.1"; $env:PORT="5210"; $env:THREADS="8"; python serve.py

与 run.py 的区别：
- 不开调试、不热重载；
- 多线程处理请求（Flask 自带的开发服务器不适合对外）；
- 日志走标准输出，交给 systemd / nohup 收集。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app  # noqa: E402

app = create_app()


def main() -> int:
    try:
        from waitress import serve
    except ImportError:
        print("缺少 waitress，请先执行：pip install waitress", file=sys.stderr)
        return 2

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5210"))
    threads = int(os.getenv("THREADS", "8"))

    config = app.config["WORLDBRANCH"]
    if config.DEBUG:
        print(
            "警告：WORLDBRANCH_DEBUG=1，生产环境应当关掉（会打印 SQL、暴露调试信息）",
            file=sys.stderr,
        )

    print(f"WorldBranch 生产模式：waitress {host}:{port}，{threads} 线程", flush=True)
    serve(app, host=host, port=port, threads=threads, ident="WorldBranch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())