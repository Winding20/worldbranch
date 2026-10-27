"""模型适配器的契约测试。

用一个本地假的 OpenAI 兼容服务，真实地验证：
- 请求发到 `/chat/completions`，带 `Authorization: Bearer <key>`
- 请求体包含 model / messages / temperature / max_tokens
- 正常响应能被正确解析
- 401 / 500 / 非法响应 / 连不上，都会变成带中文说明的 LLMError
- **任何错误信息里都不能出现 api_key**

不需要真实 Key，也不会访问外网。
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.ai.providers import LLMConfig, LLMError, OpenAICompatibleClient

FAKE_KEY = "sk-test-1234567890-should-never-leak"


class _Handler(BaseHTTPRequestHandler):
    """按类属性决定这次请求返回什么，便于逐个用例切换。"""

    mode = "ok"
    received: dict = {}

    def log_message(self, *args):  # 静音
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        type(self).received = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(body) if body else {},
        }

        if self.mode == "unauthorized":
            self.respond(401, {"error": {"message": "invalid api key"}})
        elif self.mode == "server_error":
            self.respond(500, {"error": {"message": "internal"}})
        elif self.mode == "empty":
            self.respond(200, {"choices": []})
        elif self.mode == "garbage":
            self.respond(200, {"unexpected": True})
        else:
            self.respond(
                200,
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "这是假服务的回答。"}}
                    ]
                },
            )

    def respond(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def fake_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}/v1", _Handler
    server.shutdown()
    server.server_close()


def _client(base_url: str, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        LLMConfig(
            kind="openai_compatible",
            base_url=base_url,
            model="test-model",
            api_key=kwargs.pop("api_key", FAKE_KEY),
            timeout=5,
            **kwargs,
        )
    )


def test_success_parses_content(fake_server):
    base_url, handler = fake_server
    handler.mode = "ok"
    answer = _client(base_url).chat([{"role": "user", "content": "你好"}])
    assert answer == "这是假服务的回答。"


def test_request_shape(fake_server):
    base_url, handler = fake_server
    handler.mode = "ok"
    _client(base_url).chat(
        [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户问题"},
        ]
    )
    received = handler.received
    assert received["path"].endswith("/chat/completions")
    assert received["auth"] == f"Bearer {FAKE_KEY}"
    assert received["body"]["model"] == "test-model"
    assert received["body"]["messages"][0]["role"] == "system"
    assert 0 <= received["body"]["temperature"] <= 1
    assert received["body"]["max_tokens"] > 0


def test_unauthorized_raises_without_leaking_key(fake_server):
    base_url, handler = fake_server
    handler.mode = "unauthorized"
    with pytest.raises(LLMError) as err:
        _client(base_url).chat([{"role": "user", "content": "hi"}])
    message = str(err.value)
    assert "401" in message
    assert FAKE_KEY not in message


def test_server_error_raises(fake_server):
    base_url, handler = fake_server
    handler.mode = "server_error"
    with pytest.raises(LLMError) as err:
        _client(base_url).chat([{"role": "user", "content": "hi"}])
    assert "500" in str(err.value)
    assert FAKE_KEY not in str(err.value)


@pytest.mark.parametrize("mode", ["empty", "garbage"])
def test_malformed_response_raises(fake_server, mode):
    base_url, handler = fake_server
    handler.mode = mode
    with pytest.raises(LLMError):
        _client(base_url).chat([{"role": "user", "content": "hi"}])


def test_missing_key_rejected_before_request(fake_server):
    base_url, handler = fake_server
    handler.mode = "ok"
    with pytest.raises(LLMError) as err:
        _client(base_url, api_key="").chat([{"role": "user", "content": "hi"}])
    assert "API Key" in str(err.value)


def test_missing_base_url_rejected():
    with pytest.raises(LLMError) as err:
        _client("").chat([{"role": "user", "content": "hi"}])
    assert "base_url" in str(err.value)


def test_connection_refused_raises():
    # 找一个确定没人监听的端口
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    with pytest.raises(LLMError) as err:
        _client(f"http://127.0.0.1:{port}/v1").chat([{"role": "user", "content": "hi"}])
    assert "无法连接" in str(err.value)
    assert FAKE_KEY not in str(err.value)


def test_base_url_trailing_slash_is_normalized(fake_server):
    base_url, handler = fake_server
    handler.mode = "ok"
    answer = _client(base_url + "/").chat([{"role": "user", "content": "hi"}])
    assert answer
    assert "//chat/completions" not in handler.received["path"]


# --------------------------------------------------------------------------- #
# 端到端：走真实 HTTP 适配器完成一次完整分析
# --------------------------------------------------------------------------- #
def test_full_analysis_pipeline_against_fake_server(db_session, fake_server):
    from app.ai import analyze
    from app.models import LlmProvider
    from app.services import create_branch, get_world_by_key

    base_url, handler = fake_server
    handler.mode = "ok"

    world = get_world_by_key(db_session, "tang_750")
    branch = create_branch(db_session, world, name="适配器联调", seed=3)

    provider = LlmProvider(
        name="假服务",
        kind="openai_compatible",
        base_url=base_url,
        model="test-model",
        enabled=True,
        is_default=True,
    )
    db_session.add(provider)
    db_session.flush()

    result = analyze(
        db_session,
        branch,
        question="当前局势如何？",
        provider=provider,
        api_key=FAKE_KEY,
    )

    assert result["answer"] == "这是假服务的回答。"
    assert result["provider"]["kind"] == "openai_compatible"

    # 请求确实带着 Key，且材料里有真实模拟事实
    received = handler.received
    assert received["auth"] == f"Bearer {FAKE_KEY}"
    user_content = received["body"]["messages"][-1]["content"]
    assert "【各道现状】" in user_content
    assert "河北道" in user_content

    # 但响应里不能出现 Key
    assert FAKE_KEY not in json.dumps(result, ensure_ascii=False)