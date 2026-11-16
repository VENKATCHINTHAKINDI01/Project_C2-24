"""Cloud Run start (ADR-0028 addendum 2): with C2_SANDBOX_WARM_START the sandbox is built while
the instance starts, so the first officer's request does not wait for it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def _app(warm: bool):  # type: ignore[no-untyped-def]
    return create_app(
        get_settings().model_copy(update={"sandbox": True, "sandbox_warm_start": warm})
    )


def test_warm_start_builds_the_sandbox_before_the_first_request() -> None:
    app = _app(True)
    with TestClient(app):
        assert app.state.assist_runtime.cache_info().currsize == 1


def test_without_it_the_first_assistant_call_builds_it() -> None:
    app = _app(False)
    with TestClient(app):
        assert app.state.assist_runtime.cache_info().currsize == 0


def test_requests_arriving_together_share_one_build(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Regression: functools.cache let every request that came before the first build finished
    start its own build (seen on a cold sandbox: several builds at once, minutes of CPU)."""
    import threading
    import time

    from app.agents.runtime import AssistRuntime

    calls = []
    real = AssistRuntime.build

    def slow(*a, **k):  # type: ignore[no-untyped-def]
        calls.append(1)
        time.sleep(0.3)
        return real(*a, **k)

    monkeypatch.setattr(AssistRuntime, "build", slow)
    app = _app(False)
    got: list[object] = []
    threads = [
        threading.Thread(target=lambda: got.append(app.state.assist_runtime())) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len({id(g) for g in got}) == 1
