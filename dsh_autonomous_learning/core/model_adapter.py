"""语言模型适配层。

目标（规范第十节）：
- 分阶段调用（规划/检索/提取/核验/实践/评估/反思），阶段与模型可配置；
- 统一超时、重试、限速、token/费用预算、输出格式校验、失败降级；
- 无可用模型时提供确定性 Mock，保证单元测试与离线流程可跑；
- 禁止硬编码密钥，只从环境变量读取。

设计约定：模型输出永远只是"候选材料"，不能直接改写知识状态。
知识状态升级由 core/state_machine.py 的证据规则决定。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..config import ModelConfig


class ModelError(RuntimeError):
    """模型调用失败。"""


class ModelUnavailable(ModelError):
    """未配置可用模型。"""


@dataclass
class ModelResponse:
    text: str
    model: str
    stage: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_estimate: float = 0.0
    parsed: Optional[Any] = None
    raw: Optional[Dict[str, Any]] = None
    fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "stage": self.stage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_estimate": self.cost_estimate,
            "parsed": self.parsed,
            "fallback": self.fallback,
        }


class RateLimiter:
    """极简令牌桶（每分钟上限）。"""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(1, per_minute)
        self._window_start = time.monotonic()
        self._count = 0

    def acquire(self) -> None:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count = 0
        if self._count >= self.per_minute:
            sleep_for = 60 - (now - self._window_start)
            if sleep_for > 0:
                time.sleep(min(sleep_for, 5.0))
            self._window_start = time.monotonic()
            self._count = 0
        self._count += 1


class BaseModel:
    provider = "base"

    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.rate_limit_per_min)

    def complete(
        self,
        stage: str,
        system: str,
        user: str,
        *,
        json_schema: Optional[Mapping[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ModelResponse:  # pragma: no cover - 抽象
        raise NotImplementedError

    def model_for(self, stage: str) -> str:
        return self.cfg.stages.get(stage, self.cfg.model)

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens / 1000.0 * self.cfg.price_input_per_1k
            + completion_tokens / 1000.0 * self.cfg.price_output_per_1k
        )


class NullModel(BaseModel):
    """显式禁用模型：任何调用都抛 ModelUnavailable，由调用方走规则路径。"""

    provider = "none"

    def complete(self, stage: str, system: str, user: str, **kwargs: Any) -> ModelResponse:
        raise ModelUnavailable("模型调用已被配置禁用（model.provider=none）")


_SCHEMA_PLACEHOLDERS = {
    "string": "mock",
    "number": 0,
    "integer": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _fill_schema(schema: Mapping[str, Any]) -> Any:
    """按 JSON Schema 生成确定性的占位对象，供 Mock 模型使用。"""

    stype = schema.get("type", "object")
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if stype == "object":
        required = schema.get("required") or list((schema.get("properties") or {}).keys())
        props = schema.get("properties") or {}
        out: Dict[str, Any] = {}
        for key in required:
            sub = props.get(key, {})
            out[key] = _fill_schema(sub) if sub else _SCHEMA_PLACEHOLDERS["string"]
        return out
    if stype == "array":
        item = schema.get("items") or {}
        return [_fill_schema(item)] if item else []
    return _SCHEMA_PLACEHOLDERS.get(stype, "mock")


class MockModel(BaseModel):
    """确定性模拟模型：用于单元测试与离线演示。

    行为规则（写得足够"可预期"，才能当测试替身）：
    - 传入 json_schema 时，按 schema 生成结构合法的占位 JSON；
    - 否则返回带阶段标记的固定文本；
    - 支持 ``fail_times`` 注入失败，用于测试重试；
    - 每次调用都记账，便于断言预算逻辑。
    """

    provider = "mock"

    def __init__(self, cfg: ModelConfig, *, fail_times: int = 0, latency_ms: int = 0) -> None:
        super().__init__(cfg)
        self.fail_times = fail_times
        self.latency_ms = latency_ms
        self.calls: List[Dict[str, Any]] = []

    def complete(
        self,
        stage: str,
        system: str,
        user: str,
        *,
        json_schema: Optional[Mapping[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ModelResponse:
        self.limiter.acquire()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ModelError(f"mock 注入失败（剩余 {self.fail_times} 次）")
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        payload = _fill_schema(json_schema) if json_schema else None
        text = json.dumps(payload, ensure_ascii=False) if payload is not None else f"[mock:{stage}] {user[:80]}"
        prompt_tokens = max(1, len(user) // 4)
        completion_tokens = max(1, len(text) // 4)
        response = ModelResponse(
            text=text,
            model="mock-1",
            stage=stage,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimate=0.0,
            parsed=payload,
        )
        self.calls.append({"stage": stage, "text": text, "schema": bool(json_schema)})
        return response


def _extract_json(text: str) -> Any:
    """从模型输出里尽力提取 JSON（容忍 ```json 围栏与前后废话）。"""

    text = (text or "").strip()
    if not text:
        raise ModelError("模型返回空内容")
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise ModelError("模型输出不是合法 JSON")


class OpenAICompatModel(BaseModel):
    """OpenAI 兼容 /chat/completions。"""

    provider = "openai"

    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__(cfg)
        self.api_key = os.environ.get(cfg.api_key_env, "")
        if not self.api_key:
            raise ModelUnavailable(
                f"环境变量 {cfg.api_key_env} 未设置，无法调用 {cfg.provider}"
            )
        self.base_url = cfg.base_url.rstrip("/")

    def complete(
        self,
        stage: str,
        system: str,
        user: str,
        *,
        json_schema: Optional[Mapping[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ModelResponse:
        import httpx

        self.limiter.acquire()
        model = self.model_for(stage)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] = (
                system
                + "\n\n必须只输出 JSON，且严格符合以下 JSON Schema：\n"
                + json.dumps(json_schema, ensure_ascii=False)
            )
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error = ""
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            for attempt in range(self.cfg.max_retries + 1):
                try:
                    resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code >= 400:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                        if resp.status_code in (408, 429) or resp.status_code >= 500:
                            time.sleep(0.6 * (attempt + 1))
                            continue
                        raise ModelError(last_error)
                    data = resp.json()
                    choice = (data.get("choices") or [{}])[0]
                    text = (choice.get("message") or {}).get("content", "")
                    usage = data.get("usage") or {}
                    prompt_tokens = int(usage.get("prompt_tokens", 0))
                    completion_tokens = int(usage.get("completion_tokens", 0))
                    parsed = _extract_json(text) if json_schema else None
                    return ModelResponse(
                        text=text,
                        model=model,
                        stage=stage,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_estimate=self._estimate_cost(prompt_tokens, completion_tokens),
                        parsed=parsed,
                        raw=data,
                    )
                except ModelError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    if attempt >= self.cfg.max_retries:
                        break
                    time.sleep(0.6 * (attempt + 1))
        raise ModelError(f"模型调用失败（已重试 {self.cfg.max_retries} 次）: {last_error}")


def build_model(cfg: ModelConfig) -> BaseModel:
    if cfg.provider == "mock":
        return MockModel(cfg)
    if cfg.provider == "none":
        return NullModel(cfg)
    if cfg.provider == "openai":
        return OpenAICompatModel(cfg)
    raise ModelUnavailable(f"未知 model.provider: {cfg.provider}")


__all__ = [
    "BaseModel",
    "MockModel",
    "ModelError",
    "ModelResponse",
    "ModelUnavailable",
    "NullModel",
    "OpenAICompatModel",
    "RateLimiter",
    "build_model",
]
