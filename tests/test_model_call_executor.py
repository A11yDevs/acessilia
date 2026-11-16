"""Model execution stays bounded while a provider remains blocked (#276)."""

import asyncio
import contextvars
import threading
import time
from types import SimpleNamespace

import pytest

from backend.core.agents.model_calls import (
    ModelCallRejected,
    ModelCallTimeout,
    current_model_calls,
    model_call_scope,
)
from backend.core.blocking import run_blocking
from backend.core.i18n import active_locale, reset_request_locale, set_request_locale
from backend.core.ports import RunPorts
from backend.services.model_calls import ModelCallExecutor, ModelCallLimits
from tests.core_config_support import core_config, model_config, toolbox_config


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def drained(runner):
    await until(lambda: runner.snapshot()["active"] == 0)


class Blocked:
    def __init__(self, value="answer"):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.value = value
        self.locales = []

    def __call__(self, **_kwargs):
        self.started.set()
        self.locales.append(active_locale())
        try:
            self.release.wait()
            return self.value
        finally:
            self.finished.set()


@pytest.fixture
def runner():
    service = ModelCallExecutor(ModelCallLimits(workers=1, max_pending=1))
    try:
        yield service
    finally:
        service.close(wait=True)


@pytest.mark.asyncio
async def test_running_deadline_retains_capacity_and_default_executor_stays_available(runner):
    blocked = Blocked()
    call = asyncio.create_task(runner.run(blocked, timeout=0.1, label="blocked"))
    try:
        await until(blocked.started.is_set)
        with pytest.raises(ModelCallTimeout):
            await asyncio.wait_for(call, 2)
        assert not blocked.finished.is_set()
        assert runner.snapshot()["active"] == runner.snapshot()["abandoned"] == 1
        assert runner.snapshot()["expirations"] == 1
        # One pending slot is allowed; fill it without letting inference start.
        pending = asyncio.create_task(runner.run(lambda: "pending", timeout=5, label="pending"))
        await until(lambda: runner.snapshot()["pending"] == 1)
        with pytest.raises(ModelCallRejected):
            await runner.run(lambda: "overflow", timeout=5, label="overflow")
        assert await asyncio.wait_for(run_blocking(lambda: "independent"), 2) == "independent"
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 2)
    finally:
        blocked.release.set()
        await asyncio.gather(call, return_exceptions=True)
        await drained(runner)
    assert await runner.run(lambda: "reused", timeout=1, label="reused") == "reused"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_pending_calls_are_removed_and_never_start_late(runner, cancel):
    blocked = Blocked()
    executed = []
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="active"))
    pending = None
    try:
        await until(blocked.started.is_set)
        for _ in range(12):
            pending = asyncio.create_task(runner.run(
                lambda: executed.append(True), timeout=0.03 if not cancel else 5, label="queued"
            ))
            await until(lambda: runner.snapshot()["pending"] == 1)
            if cancel:
                pending.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else ModelCallTimeout):
                await asyncio.wait_for(pending, 2)
            assert runner.snapshot()["pending"] == 0
            assert runner.snapshot()["active"] == 1
        assert executed == []
    finally:
        blocked.release.set()
        if pending is not None:
            pending.cancel()
        await asyncio.gather(active, *([pending] if pending else []), return_exceptions=True)
        await drained(runner)
    assert executed == []


@pytest.mark.asyncio
async def test_worker_checks_deadline_before_inference_even_when_loop_timer_is_delayed(runner):
    blocked = Blocked()
    executed = []
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="active"))
    pending = None
    try:
        await until(blocked.started.is_set)
        pending = asyncio.create_task(runner.run(lambda: executed.append(True), timeout=0.03, label="queued"))
        await until(lambda: runner.snapshot()["pending"] == 1)
        # Delay this loop's timer while the worker is allowed to drain the queue.
        time.sleep(0.06)
        blocked.release.set()
        time.sleep(0.03)
        with pytest.raises(ModelCallTimeout):
            await asyncio.wait_for(pending, 2)
        assert executed == []
    finally:
        blocked.release.set()
        await asyncio.gather(active, *([pending] if pending else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_saturation_is_explicit_observable_and_does_not_grow_admission(runner):
    blocked = Blocked()
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="active"))
    pending = None
    messages = []
    from backend.core.logger import logger
    sink = logger.add(messages.append, format="{message}")
    try:
        await until(blocked.started.is_set)
        pending = asyncio.create_task(runner.run(lambda: None, timeout=5, label="pending"))
        await until(lambda: runner.snapshot()["pending"] == 1)
        for _ in range(10):
            with pytest.raises(ModelCallRejected):
                await runner.run(lambda: pytest.fail("rejected work ran"), timeout=1, label="saturated")
        assert runner.snapshot()["active"] == runner.snapshot()["pending"] == 1
        assert runner.snapshot()["rejections"] == 10
        assert any("saturated" in message for message in messages)
    finally:
        blocked.release.set()
        await asyncio.gather(active, *([pending] if pending else []), return_exceptions=True)
        logger.remove(sink)


@pytest.mark.asyncio
async def test_running_cancellation_propagates_and_late_result_is_discarded(runner):
    blocked = Blocked()
    call = asyncio.create_task(runner.run(blocked, timeout=5, label="cancelled"))
    try:
        await until(blocked.started.is_set)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, 2)
        assert not blocked.finished.is_set()
        assert runner.snapshot()["abandoned"] == 1
    finally:
        blocked.release.set()
        await asyncio.gather(call, return_exceptions=True)
        await drained(runner)
    assert call.cancelled()


@pytest.mark.asyncio
async def test_each_submission_preserves_its_own_locale_including_queue_wait(runner):
    blocked = Blocked()
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="blocker"))
    pending = None
    extra = contextvars.ContextVar("submission_marker", default="unset")
    try:
        await until(blocked.started.is_set)
        token = set_request_locale("pt_BR")
        marker = extra.set("portuguese")
        try:
            pending = asyncio.create_task(runner.run(
                lambda: (active_locale(), extra.get()), timeout=5, label="portuguese"
            ))
        finally:
            reset_request_locale(token)
            extra.reset(marker)
        await until(lambda: runner.snapshot()["pending"] == 1)
        blocked.release.set()
        assert await pending == ("pt_BR", "portuguese")
        token = set_request_locale("en_US")
        try:
            assert await runner.run(lambda: (active_locale(), extra.get()), timeout=1, label="english") == ("en_US", "unset")
        finally:
            reset_request_locale(token)
    finally:
        blocked.release.set()
        await asyncio.gather(active, *([pending] if pending else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_provider_timeout_keeps_its_original_exception(runner):
    error = TimeoutError("provider timeout")
    def fail():
        raise error
    with pytest.raises(TimeoutError) as observed:
        await runner.run(fail, timeout=1, label="provider")
    # asyncio.wrap_future can reconstruct the built-in TimeoutError; the
    # provider's type/message must survive without becoming our deadline.
    assert type(observed.value) is TimeoutError
    assert str(observed.value) == "provider timeout"
    assert runner.snapshot()["expirations"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [SystemExit, KeyboardInterrupt, asyncio.CancelledError])
async def test_worker_transfers_base_exceptions_to_the_awaiter(runner, error_type):
    def fail():
        raise error_type("provider interrupted")

    with pytest.raises(error_type, match="provider interrupted"):
        await runner.run(fail, timeout=1, label="interrupted")
    assert runner.snapshot()["active"] == runner.snapshot()["expirations"] == 0
    assert await runner.run(lambda: "reused", timeout=1, label="reused") == "reused"


def test_process_gives_the_run_its_runner_the_job_config_and_its_ports(monkeypatch, tmp_path, runner):
    """The service passes all three explicitly (ADR-0016 steps 3 and 4): no
    scope, no settings, and the region cache is the service's own."""
    from backend import service

    source = tmp_path / "input.txt"
    source.write_text("content")
    received = {}

    async def execute(*_args, config, model_calls, ports, **_kwargs):
        received.update(config=config, model_calls=model_calls, ports=ports)
        return "Accessible content"

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "agente", SimpleNamespace(execute=execute))
    monkeypatch.setattr(service, "get_model_calls", lambda: runner)
    for name in ("get_cached", "set_cache", "registrar_conversao"):
        monkeypatch.setattr(service, name, noop)
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *_args: None)
    monkeypatch.setattr(service.state_manager, "obter", lambda *_args: object())
    monkeypatch.setattr(service.state_manager, "atualizar", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service.state_manager, "verificar_cancelamento", lambda *_args: None)
    job_config = core_config()

    async def request():
        result = await service.process(source, task_id="scope-wiring", config=job_config)
        assert result["source"]["name"] == source.name

    contextvars.Context().run(asyncio.run, request())

    assert received["config"] is job_config
    assert received["model_calls"] is runner
    from backend.services.cache import ContentCache

    assert isinstance(received["ports"].region_cache, ContentCache)


def test_a_run_installs_its_runner_and_restores_the_scope(monkeypatch, tmp_path, runner):
    """A fresh Context bypasses the autouse scope, as a real service entry does."""
    from types import SimpleNamespace as Namespace

    from backend.core.agents.data_agent import DataAgent
    from backend.core.agents.vision_agent import VisionAgent
    from backend.core.pipeline import orchestrator as pddl
    from backend.core.pipeline import preflight
    from tests.pddl_support import build_element, build_manifest, build_orchestrator

    observed = []

    class Stop(Exception):
        pass

    async def stage(*_args, **_kwargs):
        observed.append(current_model_calls())
        models, toolbox = model_config(), toolbox_config()
        assert DataAgent(models=models, toolbox=toolbox).model_calls is runner
        assert VisionAgent(models=models, toolbox=toolbox, region_cache=None).model_calls is runner
        raise Stop

    async def no_inspection(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pddl, "_classify_formula_regions", stage)
    monkeypatch.setattr(preflight, "inspect_source_media", no_inspection)
    orchestrator = build_orchestrator()
    manifest = build_manifest([build_element("h", "heading", text="Title")], [])
    orchestrator.information_structural = Namespace(process=lambda *a, **k: manifest)

    async def request():
        with pytest.raises(RuntimeError, match="runner must be supplied"):
            current_model_calls()
        with pytest.raises(Stop):
            await orchestrator.execute(
                tmp_path / "doc.pdf", tmp_path, config=core_config(), model_calls=runner, ports=RunPorts.none()
            )
        with pytest.raises(RuntimeError, match="runner must be supplied"):
            current_model_calls()

    contextvars.Context().run(asyncio.run, request())

    assert observed == [runner]


@pytest.mark.asyncio
async def test_close_discards_pending_work_without_joining_running_provider(runner):
    blocked = Blocked()
    executed = []
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="active"))
    pending = None
    try:
        await until(blocked.started.is_set)
        pending = asyncio.create_task(runner.run(lambda: executed.append(True), timeout=5, label="pending"))
        await until(lambda: runner.snapshot()["pending"] == 1)
        runner.close(wait=False)
        assert not blocked.finished.is_set()
        assert runner.snapshot()["active"] == 1
        assert runner.snapshot()["pending"] == 0
        for task in (active, pending):
            with pytest.raises(ModelCallRejected):
                await asyncio.wait_for(task, 2)
        with pytest.raises(ModelCallRejected):
            await runner.run(lambda: None, timeout=1, label="closed")
    finally:
        blocked.release.set()
        await asyncio.gather(active, *([pending] if pending else []), return_exceptions=True)
    assert executed == []


@pytest.mark.parametrize("agent_kind,nested", [
    ("data", False), ("vision", False), ("region-handler", False),
    ("page-handler", False), ("region-handler", True), ("page-handler", True),
])
def test_sync_call_returns_while_provider_stays_blocked(monkeypatch, runner, agent_kind, nested):
    from backend.core.agents import data_agent, model_call_policy, vision_agent
    from backend.core.pipeline.handlers.inspection import _inspect_page, _inspect_region

    blocked = Blocked(SimpleNamespace(content=None))
    for module in (data_agent, vision_agent):
        monkeypatch.setattr(module, "Agent", lambda **_kwargs: SimpleNamespace(run=blocked))
        monkeypatch.setattr(module, "get_agno_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(data_agent, "load_region_prompt", lambda _key: "prompt")
    models = model_config(data_agent_timeout_seconds=0, model_call_timeout_seconds=0)
    toolbox = toolbox_config()
    monkeypatch.setattr(model_call_policy, "CALL_DEADLINE_GRACE_SECONDS", 0.05)
    # The VisionAgent retries once; allow the second attempt to remain pending
    # and expire behind the first, still-blocked attempt.
    returned = threading.Event()
    results = []
    locales = []

    def invoke():
        if agent_kind == "data":
            results.append(asyncio.run(data_agent.DataAgent(models=models, toolbox=toolbox, model_calls=runner).process_region(b"image", "table")))
        elif agent_kind == "vision":
            results.append(asyncio.run(vision_agent.VisionAgent(region_cache=None, toolbox=toolbox, models=models, model_calls=runner).describe_region(b"image", "embedded_image")))
        elif agent_kind == "region-handler":
            results.append(_inspect_region(b"image", 1, 1, "medio", region_cache=None, toolbox=toolbox, models=models))
        else:
            try:
                _inspect_page(b"image", 1, 1, "medio", region_cache=None, toolbox=toolbox, models=models)
            except ModelCallTimeout:
                results.append(None)

    async def inside_loop():
        invoke()

    def sync_handler():
        token = set_request_locale("pt_BR")
        try:
            with model_call_scope(runner):
                if nested:
                    asyncio.run(inside_loop())
                else:
                    invoke()
                locales.append(active_locale())
        finally:
            reset_request_locale(token)
            returned.set()

    thread = threading.Thread(target=sync_handler, daemon=True)
    thread.start()
    try:
        assert blocked.started.wait(2)
        assert returned.wait(2), "asyncio.run joined the blocked provider"
        assert not blocked.finished.is_set()
        assert results == [None]
        assert locales == ["pt_BR"]
        assert blocked.locales == ["pt_BR"]
    finally:
        blocked.release.set()
        thread.join(2)
    assert not thread.is_alive()


@pytest.mark.parametrize("workers,pending", [(0, 1), (1, -1)])
def test_invalid_capacity_is_rejected(workers, pending):
    with pytest.raises(ValueError):
        ModelCallLimits(workers, pending)


@pytest.mark.asyncio
async def test_concurrent_requests_keep_independent_contexts():
    service = ModelCallExecutor(ModelCallLimits(2, 0))
    barrier = threading.Barrier(2)

    def model():
        barrier.wait(timeout=2)
        return active_locale()

    async def request(locale):
        token = set_request_locale(locale)
        try:
            return await service.run(model, timeout=2, label=locale)
        finally:
            reset_request_locale(token)

    try:
        assert await asyncio.gather(request("pt_BR"), request("en_US")) == ["pt_BR", "en_US"]
    finally:
        barrier.abort()
        service.close(wait=True)


@pytest.mark.asyncio
async def test_process_owner_does_not_replace_a_closed_pool_with_abandoned_threads(monkeypatch, runner):
    from backend.services import model_calls as owner
    monkeypatch.setattr(owner, "_owner", runner)
    blocked = Blocked()
    active = asyncio.create_task(runner.run(blocked, timeout=5, label="old-owner"))
    replacement = None
    try:
        await until(blocked.started.is_set)
        owner.shutdown_model_calls()
        assert owner.get_model_calls() is runner
        assert not blocked.finished.is_set()
        with pytest.raises(ModelCallRejected):
            await asyncio.wait_for(active, 2)
        blocked.release.set()
        await until(lambda: runner.snapshot()["active"] == 0)
        replacement = owner.get_model_calls()
        assert replacement is not runner
        assert owner.get_model_calls() is replacement
        assert await replacement.run(lambda: "new lifecycle", timeout=1, label="new") == "new lifecycle"
    finally:
        blocked.release.set()
        await asyncio.gather(active, return_exceptions=True)
        if replacement is not None:
            replacement.close(wait=True)


@pytest.mark.asyncio
async def test_serial_successes_release_capacity_before_returning():
    service = ModelCallExecutor(ModelCallLimits(1, 0))
    try:
        for value in range(8):
            assert await service.run(lambda: value, timeout=1, label="serial") == value
            assert service.snapshot()["active"] == 0
    finally:
        service.close(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan")])
async def test_a_call_requires_a_finite_nonnegative_deadline(runner, timeout):
    with pytest.raises(ValueError):
        await runner.run(lambda: pytest.fail("invalid call ran"), timeout=timeout, label="invalid")
    assert runner.snapshot()["active"] == runner.snapshot()["pending"] == 0


@pytest.mark.asyncio
async def test_an_already_expired_call_does_not_begin_inference(runner):
    with pytest.raises(ModelCallTimeout):
        await runner.run(lambda: pytest.fail("expired inference ran"), timeout=0, label="expired")
