"""摘要缓存使用的稳定指纹纯函数。"""

import hashlib
import json
from typing import Any, Mapping

SUMMARY_ALGORITHM_VERSION = "summary-v3"
SUMMARY_CLEANER_VERSION = "cleaner-v1"
SUMMARY_TRUNCATION_VERSION = "truncate-v1"
# 情绪分类与摘要彼此独立：改情绪 prompt / 标签集 / 模型只会让情绪缓存失效，
# 不会让已经跑完的摘要变成 stale（因此可以单独用 --emotion-only 补情绪）。
EMOTION_ALGORITHM_VERSION = "emotion-v1"
DEFAULT_CACHE_NAMESPACE = "summary-cache-v1"
EMOTION_CACHE_NAMESPACE = "emotion-cache-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def entry_key(entry: Mapping[str, Any]) -> str:
    return f"v1:{entry.get('date') or entry.get('entry_date')}:{entry.get('entry_type')}"


def source_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def algorithm_payload(settings: Mapping[str, Any], model: str, prompt_text: str) -> dict:
    return {
        "algorithm_version": SUMMARY_ALGORITHM_VERSION,
        "cleaner_version": SUMMARY_CLEANER_VERSION,
        "truncation_version": SUMMARY_TRUNCATION_VERSION,
        "prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "model": model,
        "temperature": float(settings["llm_temperature"]),
        "max_tokens": int(settings["llm_max_tokens"]),
        "reasoning_effort": str(settings.get("llm_reasoning_effort") or ""),
        "json_mode": bool(settings.get("llm_json_mode", False)),
        "content_head_chars": int(settings["content_head_chars"]),
        "content_tail_chars": int(settings["content_tail_chars"]),
        "max_summary_chars": int(settings["max_summary_chars"]),
    }


def emotion_payload(settings: Mapping[str, Any], model: str, prompt_text: str) -> dict:
    """情绪分类的算法指纹载荷（含标签集，改 .env 里的标签就会让情绪重算）"""
    return {
        "algorithm_version": EMOTION_ALGORITHM_VERSION,
        "label_version": str(settings.get("emotion_label_version") or ""),
        "labels": [str(label) for label in (settings.get("emotion_labels") or [])],
        "fallback": str(settings.get("emotion_fallback") or ""),
        "prompt_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "model": model,
        "temperature": float(settings.get("emotion_temperature", 0.0)),
        "max_tokens": int(settings.get("emotion_max_tokens", 0)),
        "reasoning_effort": str(settings.get("llm_reasoning_effort") or ""),
        "json_mode": False,
        "content_head_chars": int(settings["content_head_chars"]),
        "content_tail_chars": int(settings["content_tail_chars"]),
    }


def algorithm_fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def cache_key(entry_key_value: str, source_hash_value: str, algorithm_fingerprint_value: str,
              namespace: str = DEFAULT_CACHE_NAMESPACE) -> str:
    raw = "\0".join((namespace, entry_key_value, source_hash_value, algorithm_fingerprint_value))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()