"""数据库连接诊断脚本。

用法：
    python tools/test_db.py "mysql+pymysql://用户:密码@IP:3306/库名?charset=utf8mb4"
    python tools/test_db.py            # 读 backend/.env 里的 WORLDBRANCH_DATABASE_URL

它不只是「连一下」，而是把失败拆成能定位的几类：
DNS/网络、端口不通、认证失败、库不存在、字符集不对、版本过低。
"""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"


def read_env_url() -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("WORLDBRANCH_DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def parse(url: str):
    p = urlparse(url)
    return {
        "scheme": p.scheme,
        "host": p.hostname,
        "port": p.port or 3306,
        "user": unquote(p.username or ""),
        "password": unquote(p.password or ""),
        "database": (p.path or "/").lstrip("/"),
    }


def check_tcp(host: str, port: int, timeout: float = 6.0) -> tuple[bool, str]:
    try:
        ip = socket.gethostbyname(host)
    except OSError as exc:
        return False, f"DNS 解析失败：{exc}"
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True, f"{host} -> {ip}:{port} 端口可达"
    except OSError as exc:
        return False, f"端口不可达（{ip}:{port}）：{exc}"


def diagnose_connect_error(exc: Exception, info: dict) -> list[str]:
    text = str(exc)
    hints: list[str] = []

    if "Unknown database" in text:
        hints.append(f"库 `{info['database']}` 不存在 —— 回宝塔确认库名拼写")
    if "Access denied" in text:
        hints.append("账号或密码错误，或该账号不允许从你的 IP 连接")
        hints.append("→ 检查宝塔数据库的「访问权限」是否已设为「所有人」")
    if "2003" in text or "Can't connect" in text:
        hints.append("连不上服务端 —— 优先查宝塔「安全」页与腾讯云安全组是否放行 3306")
        hints.append("→ 再查 MySQL 配置 bind-address 是否为 0.0.0.0")
    if "caching_sha2_password" in text or "Authentication plugin" in text:
        hints.append("MySQL 8 认证插件需要 cryptography 包：")
        hints.append("  python -m pip install cryptography")
    if "timed out" in text.lower():
        hints.append("连接超时 —— 多半是安全组/防火墙拦了，而不是密码问题")
    if not hints:
        hints.append("未识别的错误，原文见上")
    return hints


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else read_env_url()
    if not url:
        print("没有连接串：请传参，或在 backend/.env 里配置 WORLDBRANCH_DATABASE_URL")
        return 2

    masked = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)
    print(f"连接串：{masked}")

    info = parse(url)
    print(f"类型：{info['scheme']}  主机：{info['host']}  端口：{info['port']}  库：{info['database']}  用户：{info['user']}")

    if info["scheme"].startswith("sqlite"):
        print("这是 SQLite，无需网络检查")
    else:
        ok, msg = check_tcp(info["host"], info["port"])
        print(f"[1] 网络：{msg}")
        if not ok:
            print("    网络层就不通，先解决上面这条，再谈账号密码。")
            return 1

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("缺少 SQLAlchemy：python -m pip install sqlalchemy")
        return 2

    try:
        engine = create_engine(url, future=True, connect_args={"connect_timeout": 8} if info["scheme"].startswith("mysql") else {})
        with engine.connect() as conn:
            print("[2] 认证：通过")
            if info["scheme"].startswith("mysql"):
                version = conn.execute(text("SELECT VERSION()")).scalar()
                charset = conn.execute(text("SELECT @@character_set_database")).scalar()
                collation = conn.execute(text("SELECT @@collation_database")).scalar()
                print(f"[3] 版本：{version}")
                print(f"[4] 库字符集：{charset} / {collation}")
                if version and version.split(".")[0] == "5" and version.split(".")[1] < "7":
                    print("    ⚠ 低于 5.7，JSON 列可能不可用")
                if charset not in ("utf8mb4",):
                    print("    ⚠ 建议改为 utf8mb4，否则中文可能乱码")
            else:
                print("[3] SQLite，无需版本检查")
        print("\n结论：连接可用 ✅")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[2] 认证/连接：失败 -> {type(exc).__name__}")
        print(f"    原文：{str(exc).splitlines()[0][:300]}")
        for h in diagnose_connect_error(exc, info):
            print(f"    • {h}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())