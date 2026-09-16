#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LM Studio（OpenAI 兼容 API）本地模型调用

安全约定（硬性）：

* 只允许本机地址（127.0.0.1 / localhost / ::1），非本机地址一律拒绝，
  除非在 .env 中显式设置 ``ALLOW_REMOTE_LLM=1``。日记内容因此不会被上传。
* 推理模型（Qwen3.5 等）会先输出思考再输出正文，token 预算太小会导致
  ``message.content`` 为空；用 ``LLM_REASONING_EFFORT=none`` 可关闭思考。
* 模型名称不硬编码：优先取 .env 的 ``LLM_MODEL``，留空时自动选择
  LM Studio 中第一个非 embedding 模型。

可靠性：单篇请求超时、失败重试（指数退避）、请求间隔控制。
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from scripts.batch_summary import config as bs_config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """本地模型调用失败（连接、超时、HTTP 错误、空响应等）"""


# ---------------- 地址与模型发现 ----------------

def extract_host(base_url: str) -> str:
    return (urllib.parse.urlparse(base_url or "").hostname or "").lower()


def assert_local(base_url: str, allow_remote: bool = False) -> str:
    """校验 base_url 必须是本机地址，返回 host"""
    host = extract_host(base_url)
    if not host:
        raise LLMError(f"LLM 地址无效：{base_url!r}")
    if host in bs_config.LOCAL_HOSTS:
        return host
    if allow_remote:
        logger.warning("ALLOW_REMOTE_LLM=1，正在使用非本机地址：%s", base_url)
        return host
    raise LLMError(
        f"拒绝使用非本地 LLM 地址：{base_url}"
        f"（只允许 {', '.join(bs_config.LOCAL_HOSTS)}；"
        f"如确有需要请显式设置 ALLOW_REMOTE_LLM=1）"
    )


def is_embedding_model(model_id: str) -> bool:
    """按名称判断是否为 embedding/rerank 模型"""
    name = (model_id or "").lower()
    return any(kw in name for kw in ("embed", "rerank"))


def normalize_reasoning_effort(value) -> str:
    """校验并归一化 ``reasoning_effort``

    ``""`` 表示请求里不带该参数（兼容非推理模型）；其余取值必须是
    ``config.REASONING_EFFORT_CHOICES`` 之一，否则抛 LLMError。
    """
    effort = (value or "").strip().lower()
    if not effort:
        return ""
    if effort not in bs_config.REASONING_EFFORT_CHOICES:
        raise LLMError(
            f"LLM_REASONING_EFFORT 取值不合法：{value!r}；"
            f"可选 {list(bs_config.REASONING_EFFORT_CHOICES)}，或留空表示不发送该参数"
        )
    return effort


def build_chat_payload(
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool = False,
    reasoning_effort: str = "",
) -> Dict:
    """构造 chat/completions 请求体

    推理模型（Qwen3.5 等）会把 token 先花在思考上，``message.content`` 要等思考结束
    才填充；``reasoning_effort="none"`` 可关闭思考，显著提速并省 token。
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        payload["reasoning_effort"] = normalize_reasoning_effort(reasoning_effort)
    return payload


def _http_get_json(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def list_models(base_url: str, timeout: float = 10.0) -> List[Dict]:
    """列出 LM Studio 可见模型

    先读 OpenAI 兼容的 ``/v1/models``；若原生 ``/api/v0/models`` 可用，
    则补充 type（llm / vlm / embeddings）与 state，帮助确认模型是否已加载。
    """
    base = (base_url or "").rstrip("/")
    try:
        data = _http_get_json(f"{base}/models", timeout)
    except Exception as exc:
        raise LLMError(f"无法访问 {base}/models：{exc}") from exc

    models: List[Dict] = [
        {"id": item.get("id"), "type": "unknown", "state": None}
        for item in (data.get("data") or [])
        if item.get("id")
    ]

    api_root = base[:-3] if base.endswith("/v1") else base
    try:
        native = _http_get_json(f"{api_root}/api/v0/models", timeout)
        info = {item.get("id"): item for item in (native.get("data") or [])}
        for model in models:
            detail = info.get(model["id"])
            if detail:
                model["type"] = detail.get("type") or model["type"]
                model["state"] = detail.get("state")
    except Exception:
        pass  # 原生接口不可用时忽略，只少一点信息

    for model in models:
        if model["type"] == "unknown":
            model["type"] = "embeddings" if is_embedding_model(model["id"]) else "llm"
    return models


def pick_chat_model(models: List[Dict]) -> Optional[str]:
    """选择第一个非 embedding 模型"""
    for model in models:
        if model.get("type") != "embeddings" and not is_embedding_model(model["id"]):
            return model["id"]
    return None


# ---------------- 客户端 ----------------

class LLMClient:
    """LM Studio 对话补全客户端（本地、可重试、限速）"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        interval: Optional[float] = None,
        max_retries: Optional[int] = None,
        json_mode: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        allow_remote: Optional[bool] = None,
    ):
        settings = bs_config.get_settings()
        self.base_url = (base_url or settings["llm_base_url"]).rstrip("/")
        self.model = (model or settings["llm_model"]).strip()
        self.timeout = float(timeout if timeout is not None else settings["llm_timeout"])
        self.max_tokens = int(max_tokens if max_tokens is not None else settings["llm_max_tokens"])
        self.temperature = float(
            temperature if temperature is not None else settings["llm_temperature"]
        )
        self.interval = float(
            interval if interval is not None else bs_config.REQUEST_INTERVAL_SECONDS
        )
        self.max_retries = int(
            max_retries if max_retries is not None else bs_config.MAX_RETRIES
        )
        self.json_mode = bool(json_mode if json_mode is not None else settings["llm_json_mode"])
        # None = 用 .env 的值；显式传 "" 表示请求里不带该参数
        self.reasoning_effort = normalize_reasoning_effort(
            reasoning_effort if reasoning_effort is not None
            else settings.get("llm_reasoning_effort", "")
        )
        self.allow_remote = bool(
            allow_remote if allow_remote is not None else settings["allow_remote_llm"]
        )
        # 非本机地址在此直接抛错，避免任何日记内容离开本机
        self.host = assert_local(self.base_url, self.allow_remote)
        self._last_call = 0.0
        self.call_count = 0

    # -- 模型解析 --
    def resolve_model(self) -> str:
        """返回实际使用的模型名（.env 未配置时自动发现）"""
        if self.model:
            return self.model
        models = list_models(self.base_url, min(self.timeout, 10.0))
        picked = pick_chat_model(models)
        if not picked:
            raise LLMError(
                "LM Studio 中没有可用的对话模型（只看到 embedding 模型）。"
                "请先在 LM Studio 中加载 Qwen3.5-9B，或在 .env 中设置 LLM_MODEL。"
            )
        self.model = picked
        logger.info("自动选择对话模型：%s", picked)
        return picked

    # -- 限速 --
    def _respect_interval(self):
        if self.interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)

    # -- 请求体 --
    def build_payload(self, prompt: str) -> Dict:
        """构造 chat/completions 请求体"""
        return build_chat_payload(
            prompt,
            model=self.resolve_model(),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            json_mode=self.json_mode,
            reasoning_effort=self.reasoning_effort,
        )

    # -- 调用 --
    def chat(self, prompt: str) -> str:
        """发送单条 user 消息，返回模型文本；失败抛 LLMError"""
        payload = self.build_payload(prompt)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/chat/completions"

        last_error = "未知错误"
        for attempt in range(1, self.max_retries + 1):
            self._respect_interval()
            try:
                request = urllib.request.Request(
                    url, data=body, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                self.call_count += 1
                if isinstance(data, dict) and data.get("error"):
                    raise LLMError(f"服务返回错误：{data['error']}")
                choices = data.get("choices") or []
                choice = choices[0] if choices else {}
                message = choice.get("message") or {}
                content = message.get("content") or ""
                if not content.strip():
                    raise LLMError(self._empty_response_error(choice, message, data))
                return content
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    detail = ""
                last_error = f"HTTP {exc.code} {exc.reason} {detail}".strip()
            except urllib.error.URLError as exc:
                last_error = f"连接失败：{exc.reason}"
            except LLMError as exc:
                last_error = str(exc)
            except Exception as exc:  # 超时、JSON 解析失败等
                last_error = f"{type(exc).__name__}: {exc}"
            finally:
                self._last_call = time.monotonic()

            if attempt < self.max_retries:
                backoff = bs_config.RETRY_BACKOFF_BASE ** (attempt - 1)
                logger.warning(
                    "调用失败（第 %d/%d 次）：%s；%.1fs 后重试",
                    attempt, self.max_retries, last_error, backoff,
                )
                time.sleep(backoff)

        raise LLMError(f"重试 {self.max_retries} 次仍失败：{last_error}")

    def _empty_response_error(self, choice: Dict, message: Dict, data: Dict) -> str:
        """content 为空时的可诊断原因

        推理模型把 token 预算全花在思考上（``reasoning_content`` 有内容、
        ``finish_reason=length``）是最常见的情况，错误信息里直接给出解法。
        """
        finish = choice.get("finish_reason")
        reasoning = message.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        text = "模型返回内容为空"
        if reasoning:
            text += f"（仅有思考内容 {len(reasoning)} 字"
            if reasoning_tokens:
                text += f"，reasoning_tokens={reasoning_tokens}"
            text += "）"
        if finish == "length":
            text += (
                f"；finish_reason=length：被 max_tokens={self.max_tokens} 截断。"
                "若是推理模型，请设置 LLM_REASONING_EFFORT=none 关闭思考，"
                "或调大 LLM_MAX_TOKENS（建议同时调大 LLM_TIMEOUT）"
            )
        return text

    def ping(self) -> str:
        """连通性测试（返回模型回复文本）"""
        return self.chat("请只回复两个字：正常")