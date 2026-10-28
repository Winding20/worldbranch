"""启动脚本健康检查。

Windows 的 cmd.exe 对 start.bat 有两个硬要求，踩过一次：
  - 必须是 CRLF 换行（LF 会让它把命令切成半截）
  - 最好不要出现中文（UTF-8 无 BOM 时按本地代码页解析，会乱码甚至报错）

这里把它们固定成可检查的规则，避免以后又改坏。

    python tools/check_launcher.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "start.bat"
SH = ROOT / "start.sh"


def check_bat() -> list[str]:
    problems: list[str] = []
    if not BAT.exists():
        return ["start.bat 不存在"]

    raw = BAT.read_bytes()
    if b"\r\n" not in raw:
        problems.append("start.bat 没有 CRLF 换行（cmd.exe 会解析出错）")
    # 允许的行尾只有 \r\n，出现裸 \n 就要报
    stripped = raw.replace(b"\r\n", b"")
    if b"\n" in stripped:
        problems.append("start.bat 含裸 LF 换行")

    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        problems.append("start.bat 含非 ASCII 字符（中文提示请交给 python 打印）")

    text = raw.decode("utf-8", errors="replace")
    if "bootstrap.py" not in text:
        problems.append("start.bat 没有调用 tools/bootstrap.py")
    return problems


def check_sh() -> list[str]:
    problems: list[str] = []
    if not SH.exists():
        return ["start.sh 不存在"]
    text = SH.read_text(encoding="utf-8")
    if not text.startswith("#!"):
        problems.append("start.sh 缺少 shebang")
    if "bootstrap.py" not in text:
        problems.append("start.sh 没有调用 tools/bootstrap.py")
    return problems


def main() -> int:
    problems = check_bat() + check_sh()
    if problems:
        for item in problems:
            print(f"✗ {item}")
        return 1
    print("✓ start.bat 为 ASCII + CRLF，两个入口都指向 bootstrap.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())