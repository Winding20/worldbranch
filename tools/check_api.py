"""接口自检：对着一个运行中的地址逐项确认。

    python tools/check_api.py http://127.0.0.1:5210
    python tools/check_api.py http://127.0.0.1:5210

只做只读检查，不改数据。任何一项失败以非 0 退出。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5210").rstrip("/")

CHECKS: list[tuple[str, str, str]] = [
    # (说明, 路径, 期望内容之一)
    ("健康检查", "/api/health", '"status"'),
    ("前端入口", "/app/", "index-"),
    ("世界列表", "/api/worlds", "tang_755"),
    ("唐朝切片", "/api/worlds/tang_755", "安史之乱"),
    ("知识库", "/api/ai/worlds/tang_755/knowledge", "title"),
    ("分支列表", "/api/worlds/tang_755/branches", "["),
]


def fetch(path: str) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main() -> int:
    print(f"检查目标：{BASE}\n")
    failed = 0
    for name, path, needle in CHECKS:
        try:
            status, body = fetch(path)
            ok = status == 200 and needle in body
            print(f"{'✓' if ok else '✗'} {name:<10} {path:<34} {status}")
            if not ok:
                failed += 1
                print(f"    期望包含 {needle!r}，实际长度 {len(body)}")
        except urllib.error.HTTPError as err:
            failed += 1
            print(f"✗ {name:<10} {path:<34} HTTP {err.code}")
        except (urllib.error.URLError, OSError) as err:
            failed += 1
            print(f"✗ {name:<10} {path:<34} 连接失败：{err}")

    # 分支配对：确保能读到决策与状态
    try:
        _, body = fetch("/api/worlds/tang_755/branches")
        branches = json.loads(body)
        if branches:
            bid = branches[0]["id"]
            for name, path in (
                ("分支状态", f"/api/branches/{bid}/state"),
                ("待决事项", f"/api/branches/{bid}/decisions"),
                ("各军", f"/api/branches/{bid}/armies"),
            ):
                status, _ = fetch(path)
                ok = status == 200
                print(f"{'✓' if ok else '✗'} {name:<10} {path:<34} {status}")
                if not ok:
                    failed += 1
        else:
            print("· 尚无分支（正常，首次打开会创建）")
    except Exception as err:  # noqa: BLE001 - 自检脚本，任何异常都算失败
        failed += 1
        print(f"✗ 分支配对检查失败：{err}")

    print()
    if failed:
        print(f"✗ {failed} 项未通过")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())