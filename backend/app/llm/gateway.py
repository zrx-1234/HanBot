"""LLM 网关（design §8）：统一入口，选源、重试、usage 记账。

M3 范围：单源（priority 最小且 enabled）、单源重试（lessons 2.3 参数）、
每次成功调用写 usage_log。多源降级切换是 P2-1 的事，此处不预做。
"""

import asyncio
import json
import random
from collections.abc import AsyncIterator

from sqlalchemy import select

from app.config import Settings
from app.db import models
from app.db.db import asession_scope
from app.llm.types import MessageDoneEvent, StreamEvent, UMessage


class LLMError(Exception):
    """LLM 调用错误基类。"""


class TransientLLMError(LLMError):
    """可重试错误：429 速率型、5xx、超时、断连。"""


class FatalLLMError(LLMError):
    """不可重试错误：401/403 认证失败、4xx 请求本身错。"""


class NoSourceError(LLMError):
    """没有任何可用源。"""


class LLMUnavailableError(LLMError):
    """重试预算耗尽/熔断。"""


# lessons 2.3 重试参数
_BASE_DELAY = 0.5
_MAX_DELAY = 32.0
_JITTER_RATIO = 0.25
_MAX_ATTEMPTS = 10
_CIRCUIT_BREAK = 3

_sleep = asyncio.sleep


async def _select_source(st: Settings) -> models.LlmSourceRow:
    async with asession_scope(st) as s:
        row = (
            await s.execute(
                select(models.LlmSourceRow)
                .where(models.LlmSourceRow.enabled.is_(True))
                .order_by(models.LlmSourceRow.priority, models.LlmSourceRow.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NoSourceError("没有启用的 LLM 源，请先在设置页配置")
        # 脱离 session 前取需要的值
        return models.LlmSourceRow(
            id=row.id,
            name=row.name,
            format=row.format,
            base_url=row.base_url,
            api_key_encrypted=row.api_key_encrypted,
            models=row.models,
        )


def _default_model(source: models.LlmSourceRow) -> str:
    models_list = json.loads(source.models)
    if not models_list:
        raise NoSourceError(f"源 {source.name} 没有配置模型")
    return models_list[0]["name"]


async def _stream(**kwargs) -> AsyncIterator[StreamEvent]:  # type: ignore[no-untyped-def]
    """实际调用适配器。独立函数便于测试打桩。"""
    from anthropic import AsyncAnthropic

    from app.crypto import decrypt_value
    from app.llm.anthropic_adapter import stream_anthropic

    client = AsyncAnthropic(
        base_url=kwargs["base_url"],
        api_key=decrypt_value(kwargs["data_key"], kwargs["api_key_encrypted"]),
        max_retries=0,  # 重试我们自己管，SDK 的关掉
    )
    return stream_anthropic(
        client=client,
        model=kwargs["model"],
        system=kwargs["system"],
        messages=kwargs["messages"],
        tools=kwargs["tools"],
        max_tokens=kwargs.get("max_tokens", 8192),
    )


async def _record_usage(
    st: Settings, source_id: int, model: str, ev: MessageDoneEvent, task_uuid: str | None
) -> None:
    async with asession_scope(st) as s:
        s.add(
            models.UsageLogRow(
                task_uuid=task_uuid,
                source_id=source_id,
                model=model,
                tokens_in=ev.usage.input_tokens,
                tokens_out=ev.usage.output_tokens,
                cached_tokens=ev.usage.cached_tokens,
                cache_creation_tokens=ev.usage.cache_creation_tokens,
            )
        )


async def _mark_degraded(st: Settings, source_id: int, error: str) -> None:
    async with asession_scope(st) as s:
        row = (
            await s.execute(select(models.LlmSourceRow).where(models.LlmSourceRow.id == source_id))
        ).scalar_one()
        row.status = "degraded"
        row.last_error = error[:500]


def _retry_delay(attempt: int) -> float:
    """基础延迟 500ms、指数退避 min(500×2^(n-1), 32s)、25% 抖动。"""
    base = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
    return base * (1 + random.uniform(-_JITTER_RATIO, _JITTER_RATIO))


async def chat(
    st: Settings,
    messages: list[UMessage],
    *,
    system: str = "",
    tools: list[dict] | None = None,
    task_uuid: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """一次 LLM 对话调用：选源→流式（含重试）→usage 落库。

    yield 归一化流式事件；MessageDoneEvent 恒为最后一个。
    """
    source = await _select_source(st)
    model = _default_model(source)
    async for ev in _attempt_loop(
        st, source, model, messages, system, tools or [], task_uuid=task_uuid
    ):
        yield ev


async def _attempt_loop(
    st: Settings,
    source: models.LlmSourceRow,
    model: str,
    messages: list[UMessage],
    system: str,
    tools: list[dict],
    task_uuid: str | None = None,
) -> AsyncIterator[StreamEvent]:
    failures = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            stream = await _stream(
                base_url=source.base_url,
                data_key=st.data_key,
                api_key_encrypted=source.api_key_encrypted,
                model=model,
                system=system,
                messages=messages,
                tools=tools,
            )
            final: MessageDoneEvent | None = None
            async for ev in stream:
                if isinstance(ev, MessageDoneEvent):
                    final = ev
                yield ev
            if final is not None:
                await _record_usage(st, source.id, model, final, task_uuid=task_uuid)
            return
        except FatalLLMError:
            raise
        except Exception as e:  # TransientLLMError 与未分类异常（网络/解析）
            failures += 1
            if failures >= _CIRCUIT_BREAK:
                await _mark_degraded(st, source.id, str(e))
                raise LLMUnavailableError(f"连续 {failures} 次失败：{e}") from e
            if attempt < _MAX_ATTEMPTS:
                await _sleep(_retry_delay(attempt))
