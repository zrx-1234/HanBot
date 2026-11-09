"""LLM 网关（design §8）：选源、单源重试（lessons 2.3 参数）、usage 落库。

M3 单源：取 priority 最小且 enabled 的源；重试参数照抄 lessons 2.3；
每次成功调用写一行 usage_log（含缓存 token 双列）。
"""

import pytest
from sqlalchemy import select

from app.config import Settings
from app.crypto import encrypt_value
from app.db import init_db, models
from app.db.db import asession_scope
from app.llm import gateway
from app.llm.types import MessageDoneEvent, TextBlock, UMessage, Usage


async def _add_source(settings: Settings, name="s1", priority=100, enabled=True) -> int:
    async with asession_scope(settings) as s:
        row = models.LlmSourceRow(
            name=name,
            format="anthropic",
            base_url="https://api.example.com",
            api_key_encrypted=encrypt_value(settings.data_key or "k", "sk-test"),
            models='[{"name": "glm-latest", "price_in": 1.0, "price_out": 2.0}]',
            priority=priority,
            enabled=enabled,
            status="ok",
        )
        s.add(row)
        await s.flush()
        return row.id


@pytest.fixture
def src_settings(settings: Settings) -> Settings:
    init_db(settings)
    return settings


def _done_event(text="ok", in_tok=10, out_tok=20, cached=0, cache_new=0) -> MessageDoneEvent:
    return MessageDoneEvent(
        message=UMessage(role="assistant", blocks=[TextBlock(text=text)]),
        stop_reason="end_turn",
        usage=Usage(
            input_tokens=in_tok, output_tokens=out_tok,
            cached_tokens=cached, cache_creation_tokens=cache_new,
        ),
    )


@pytest.mark.anyio
async def test_gateway_selects_highest_priority_enabled_source(src_settings, monkeypatch):
    await _add_source(src_settings, "low", priority=200)
    await _add_source(src_settings, "high", priority=10)
    await _add_source(src_settings, "disabled", priority=1, enabled=False)

    picked: list[str] = []

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        picked.append(kw["model"])

        async def _gen():
            yield _done_event()

        return _gen()

    monkeypatch.setattr(gateway, "_stream", fake_stream)
    out = [
        ev
        async for ev in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        )
    ]
    assert picked == ["glm-latest"]  # 用该源 models 列表第一个
    assert isinstance(out[-1], MessageDoneEvent)


@pytest.mark.anyio
async def test_gateway_no_source_raises(src_settings):
    with pytest.raises(gateway.NoSourceError):
        async for _ in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        ):
            pass


@pytest.mark.anyio
async def test_gateway_writes_usage_log(src_settings, monkeypatch):
    sid = await _add_source(src_settings)

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        async def _gen():
            yield _done_event(in_tok=100, out_tok=50, cached=80, cache_new=30)

        return _gen()

    monkeypatch.setattr(gateway, "_stream", fake_stream)
    _ = [
        ev
        async for ev in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        )
    ]

    async with asession_scope(src_settings) as s:
        rows = (await s.execute(select(models.UsageLogRow))).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.source_id == sid
    assert r.model == "glm-latest"
    assert r.tokens_in == 100
    assert r.tokens_out == 50
    assert r.cached_tokens == 80
    assert r.cache_creation_tokens == 30


@pytest.mark.anyio
async def test_gateway_retries_transient_errors(src_settings, monkeypatch):
    """429/5xx/超时重试；重试成功则调用方无感知（lessons 2.2/2.3）。"""
    await _add_source(src_settings)
    attempts = {"n": 0}

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise gateway.TransientLLMError("HTTP 429")

        async def _gen():
            yield _done_event()

        return _gen()

    # 重试 sleep 打桩，不等真时间
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(gateway, "_sleep", fake_sleep)
    monkeypatch.setattr(gateway, "_stream", fake_stream)

    out = [
        ev
        async for ev in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        )
    ]
    assert attempts["n"] == 3
    assert isinstance(out[-1], MessageDoneEvent)
    # 基础延迟 500ms，指数退避：两次重试分别 500*2^0, 500*2^1（抖动前）
    assert sleeps[0] == pytest.approx(0.5, abs=0.5)
    assert sleeps[1] == pytest.approx(1.0, abs=1.0)


@pytest.mark.anyio
async def test_gateway_auth_error_no_retry(src_settings, monkeypatch):
    """401/403 是配置问题，重试无意义——立即失败（lessons 2.3）。"""
    await _add_source(src_settings)
    attempts = {"n": 0}

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        raise gateway.FatalLLMError("HTTP 401")

    monkeypatch.setattr(gateway, "_stream", fake_stream)
    with pytest.raises(gateway.FatalLLMError):
        async for _ in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        ):
            pass
    assert attempts["n"] == 1


@pytest.mark.anyio
async def test_gateway_circuit_breaks_after_consecutive_failures(src_settings, monkeypatch):
    """连续 3 次失败熔断，不再重试满 10 次预算（lessons 2.3）。"""
    await _add_source(src_settings)
    attempts = {"n": 0}

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        raise gateway.TransientLLMError("HTTP 500")

    async def fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(gateway, "_sleep", fake_sleep)
    monkeypatch.setattr(gateway, "_stream", fake_stream)
    with pytest.raises(gateway.LLMUnavailableError):
        async for _ in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        ):
            pass
    assert attempts["n"] == 3  # 熔断：3 次，不是 10 次


@pytest.mark.anyio
async def test_gateway_marks_source_degraded_after_failure(src_settings, monkeypatch):
    await _add_source(src_settings)

    async def fake_stream(**kw):  # type: ignore[no-untyped-def]
        raise gateway.TransientLLMError("HTTP 500")

    async def fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(gateway, "_sleep", fake_sleep)
    monkeypatch.setattr(gateway, "_stream", fake_stream)
    with pytest.raises(gateway.LLMUnavailableError):
        async for _ in gateway.chat(
            src_settings, [UMessage(role="user", blocks=[TextBlock(text="hi")])]
        ):
            pass

    async with asession_scope(src_settings) as s:
        rows = (await s.execute(select(models.LlmSourceRow))).scalars().all()
    assert rows[0].status == "degraded"
    assert rows[0].last_error is not None
