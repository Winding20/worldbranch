"""模型适配层。

**唯一的厂商相关代码就集中在这里。** 上层只认识 ``LLMClient.chat()``，
换厂商只需要新增一个适配器，业务代码一行都不用改。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """调用模型失败。绝不把 api_key 放进错误信息里。"""


@dataclass
class LLMConfig:
    kind: str = "openai_compatible"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = 60
    max_tokens: int = 900
    temperature: float = 0.3


class LLMClient:
    """适配器基类。"""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def chat(self, messages: list[dict[str, str]]) -> str:  # pragma: no cover - 抽象
        raise NotImplementedError

    # -- 公共工具 -------------------------------------------------- #
    def _post(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise LLMError(f"模型服务返回 {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"无法连接模型服务：{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError("模型服务超时") from exc


class OpenAICompatibleClient(LLMClient):
    """OpenAI /chat/completions 协议。

    覆盖 DeepSeek、Kimi、通义千问、智谱、MiniMax、Ollama、vLLM 等。
    """

    def chat(self, messages: list[dict[str, str]]) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if not base:
            raise LLMError("未配置 base_url")
        if not self.config.api_key:
            raise LLMError("未提供 API Key（请在界面里填写你自己的 Key）")

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        data = self._post(f"{base}/chat/completions", payload, headers)

        choices = data.get("choices") or []
        if not choices:
            raise LLMError("模型返回内容为空")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise LLMError("模型返回内容为空")
        return content.strip()


class MockClient(LLMClient):
    """离线适配器：不发网络请求，用确定性文本占位。

    用于测试与演示，也是"没有配置 Key 时"的可选降级方案。
    """

    def chat(self, messages: list[dict[str, str]]) -> str:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return (
            "【离线模拟回答】当前未调用真实模型。\n"
            f"收到的材料长度：{len(user)} 字。\n"
            "依据材料可以看到：该世界在本期出现了粮食与民变相关的连锁变化，"
            "具体数值与因果链请见事件流。配置你自己的模型后可获得真正的分析。"
        )


ADAPTERS: dict[str, type[LLMClient]] = {
    "openai_compatible": OpenAICompatibleClient,
    "mock": MockClient,
}


def build_client(config: LLMConfig) -> LLMClient:
    adapter = ADAPTERS.get(config.kind)
    if adapter is None:
        raise LLMError(f"不支持的适配器类型: {config.kind}")
    return adapter(config)


def known_kinds() -> list[str]:
    return sorted(ADAPTERS)