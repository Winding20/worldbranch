"""GitHub 设备码授权：拿一个只够推送本仓库的 token。

流程（OAuth 2.0 Device Authorization Grant，GitHub 官方支持）：
  1. 向 github.com/login/device/code 申请一次性代码
  2. 用户在浏览器里输入该代码并同意
  3. 轮询 access_token 直到授权完成

token 只写入 .tmp（不进仓库、不进日志），用完可让用户在
Settings → Applications 里撤销 GitHub CLI 授权。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / ".tmp" / "gh_token.txt"

#: GitHub CLI 的公开 client_id（OAuth App，开源可见）
CLIENT_ID = "178c6fc778ccc68e1d6a"
SCOPE = "public_repo"


def post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "worldbranch-deploy",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    start = post(
        "https://github.com/login/device/code",
        {"client_id": CLIENT_ID, "scope": SCOPE},
    )
    device = start["device_code"]
    print("=" * 60)
    print(" 请在浏览器打开：", start["verification_uri"])
    print(" 输入代码：      ", start["user_code"])
    print("=" * 60, flush=True)

    interval = int(start.get("interval", 5))
    deadline = time.time() + int(start.get("expires_in", 900)) - 10
    while time.time() < deadline:
        time.sleep(interval)
        try:
            res = post(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": CLIENT_ID,
                    "device_code": device,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except Exception as exc:  # 网络抖动不算失败，继续轮询
            print(f"  轮询出错（继续）：{exc}", flush=True)
            continue

        err = res.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            print("授权失败：", err, res.get("error_description", ""), flush=True)
            return 1

        token = res.get("access_token")
        if not token:
            print("没拿到 token：", res, flush=True)
            return 1

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token, encoding="utf-8")
        print("✓ 授权成功，token 已保存到 .tmp/gh_token.txt", flush=True)
        return 0

    print("✗ 超时未授权", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())