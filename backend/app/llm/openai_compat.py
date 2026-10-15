from typing import Iterator
from .base import LLMClient
import openai


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容协议客户端"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

        if not base_url:
            raise ValueError("base_url 不能为空")
        if not api_key:
            raise ValueError("api_key 不能为空")
        if not model:
            raise ValueError("model 不能为空")

        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0
        )

    def stream(self, messages: list[dict], max_tokens: int = 8000, timeout: float | None = None) -> Iterator[str]:
        """流式返回响应"""
        try:
            kwargs = dict(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=max_tokens,
            )
            if timeout is not None:
                kwargs["timeout"] = timeout
            response = self.client.chat.completions.create(**kwargs)

            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
        except Exception as e:
            raise Exception(f"LLM 调用失败: {str(e)}")

    def chat(self, messages: list[dict], max_tokens: int = 8000, timeout: float | None = None) -> str:
        """非流式返回响应（注意：部分网关对非流式响应加外壳封装，可能导致解析失败，
        优先使用 complete()）。"""
        try:
            kwargs = dict(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
            )
            if timeout is not None:
                kwargs["timeout"] = timeout
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            raise Exception(f"LLM 调用失败: {str(e)}")

    def complete(self, messages: list[dict], max_tokens: int = 8000, timeout: float | None = None) -> str:
        """通过流式接口收齐全部输出并返回完整文本。

        兼容性优先：流式 SSE 是各网关最标准的通道（非流式响应可能被网关
        额外封装，如 cline 的 {"data": {...}} 外壳，导致 SDK 解析失败）。
        """
        return "".join(self.stream(messages, max_tokens=max_tokens, timeout=timeout))