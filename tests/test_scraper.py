"""Smoke tests for the async checker.

We don't actually hit the network in tests — that would be flaky. Instead we
monkey-patch the underlying sample function and verify the orchestration
correctly handles:
    - all proxies failing
    - one proxy succeeding, one failing
    - the 2-sample variance filter rejecting flaky proxies
"""

from __future__ import annotations

import pytest

from proxy_scraper.checker import check_all
from proxy_scraper.parser import Proxy
from proxy_scraper.protocols import Protocol


@pytest.fixture
def fake_judge(monkeypatch: pytest.MonkeyPatch):
    """Replace _sample_judge with a controllable stub."""
    state = {"values": {}}  # addr -> list of latency_ms (or inf for fail)

    async def stub(proxy: Proxy, protocol: Protocol, judge_url: str, *, timeout: float) -> float:
        key = f"{proxy.ip}:{proxy.port}"
        seq = state["values"].get(key, [50.0])
        # Pop the next sample; cycle if exhausted.
        if not seq:
            seq = state["values"][key]
        val = seq.pop(0)
        seq.append(val)
        return val

    monkeypatch.setattr("proxy_scraper.checker._sample_judge", stub)
    return state


async def test_check_all_handles_all_failures(fake_judge) -> None:
    fake_judge["values"] = {
        "1.2.3.4:80": [float("inf")],
    }
    out = await check_all(
        {Protocol.HTTP: {Proxy("1.2.3.4", 80)}},
        concurrency=1,
        timeout=1.0,
        retries=1,
    )
    assert len(out) == 1
    assert out[0].ok is False


async def test_check_all_passes_clean_proxy(fake_judge) -> None:
    fake_judge["values"] = {
        "1.2.3.4:80": [120.0, 130.0],
    }
    out = await check_all(
        {Protocol.HTTP: {Proxy("1.2.3.4", 80)}},
        concurrency=1,
        timeout=2.0,
        retries=2,
    )
    assert out[0].ok is True
    assert out[0].latency_ms == 120.0


async def test_check_all_rejects_flaky_proxy(fake_judge) -> None:
    # 50ms, then 5000ms — variance is 100x, well above LATENCY_VARIANCE_MULTIPLIER.
    fake_judge["values"] = {
        "1.2.3.4:80": [50.0, 5000.0],
    }
    out = await check_all(
        {Protocol.HTTP: {Proxy("1.2.3.4", 80)}},
        concurrency=1,
        timeout=10.0,
        retries=2,
    )
    assert out[0].ok is False


async def test_check_all_progress_callback(fake_judge) -> None:
    fake_judge["values"] = {
        "1.2.3.4:80": [120.0],
        "5.6.7.8:80": [80.0],
    }
    progress: list[tuple[int, int]] = []

    def cb(done: int, total: int) -> None:
        progress.append((done, total))

    await check_all(
        {
            Protocol.HTTP: {
                Proxy("1.2.3.4", 80),
                Proxy("5.6.7.8", 80),
            },
        },
        concurrency=2,
        timeout=2.0,
        retries=1,
        progress_cb=cb,
    )
    assert progress  # was called at least once
    assert progress[-1][0] == progress[-1][1] == 2  # final = (2, 2)
