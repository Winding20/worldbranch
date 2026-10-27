"""开发入口。

    python run.py

默认监听 0.0.0.0，同一局域网内的手机、平板可以直接访问；
只想本机访问时设 HOST=127.0.0.1。

    $env:HOST = "127.0.0.1"; python run.py
    $env:PORT = "5211"; python run.py
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app  # noqa: E402

app = create_app()


def _lan_addresses() -> list[str]:
    """列出本机可能的局域网地址，方便直接照着输到手机上。"""
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5210"))
    host = os.getenv("HOST", "0.0.0.0")
    debug = app.config["WORLDBRANCH"].DEBUG

    print(f"WorldBranch 监听 {host}:{port}")
    if host == "0.0.0.0":
        print("  本机：  http://127.0.0.1:%d/" % port)
        for ip in _lan_addresses():
            print(f"  局域网：http://{ip}:{port}/   ← 手机用这个（需同一 Wi-Fi）")
        print("  ※ 手机连不上多半是 Windows 防火墙挡了入站，见 docs/手机访问.md")
    app.run(host=host, port=port, debug=debug)