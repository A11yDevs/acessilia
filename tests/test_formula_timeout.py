"""CPU-only process/protocol tests; no Docling, network, weights or inference."""

import io
import json
import os
import runpy
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from backend.tools import formula_tools


@pytest.fixture
def temporary_files(monkeypatch, tmp_path):
    opened = []
    original = formula_tools.tempfile.TemporaryFile

    def temporary_file(*args, **kwargs):
        handle = original(*args, dir=tmp_path, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(formula_tools.tempfile, "TemporaryFile", temporary_file)
    yield opened
    assert all(handle.closed for handle in opened)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", ["bad", "", "0", "-1", "nan", "NaN", "inf", "-inf", "1e999"])
def test_invalid_timeout_is_import_safe_and_uses_default(monkeypatch, value):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", value)
    namespace = runpy.run_path(formula_tools.__file__)
    assert namespace["_codeformula_timeout"]() == 120.0


@pytest.mark.parametrize("value, expected", [(None, 120.0), ("0.25", 0.25), ("300", 300.0), (" 1.5 ", 1.5)])
def test_timeout_accepts_positive_finite_seconds(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("FORMULA_CODEFORMULA_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", value)
    assert formula_tools._codeformula_timeout() == expected


def _mock_child(monkeypatch, payload=b'{"latex":"x=1"}', returncode=0):
    process = Mock(pid=123456789)
    process.wait.return_value = returncode

    def launch(command, **kwargs):
        assert command == [sys.executable, "-m", "backend.tools.formula_worker", str(kwargs["pass_fds"][0])]
        assert kwargs["stdin"].read() == b"crop"
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["shell"] is False
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
        os.write(kwargs["pass_fds"][0], payload)
        return process

    launcher = Mock(side_effect=launch)
    killer = Mock()
    monkeypatch.setattr(formula_tools.subprocess, "Popen", launcher)
    monkeypatch.setattr(formula_tools.os, "killpg", killer)
    return process, launcher, killer


def test_timeout_budget_includes_process_startup(monkeypatch, temporary_files):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "10")
    clock = iter([100.0, 103.5])
    monkeypatch.setattr(formula_tools.time, "monotonic", lambda: next(clock))
    process, _, killer = _mock_child(monkeypatch)
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    assert process.wait.call_args_list[0].kwargs["timeout"] == 6.5
    killer.assert_not_called()
    assert process.wait.call_args_list[-1].args == ()
    assert process.wait.call_args_list[-1].kwargs == {}


def test_startup_consuming_budget_is_timeout(monkeypatch, temporary_files):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "1")
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(formula_tools.time, "monotonic", lambda: next(clock))
    process, _, killer = _mock_child(monkeypatch)
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    killer.assert_called_once_with(process.pid, signal.SIGKILL)
    assert process.wait.call_count == 2


def test_timeout_kills_waits_and_next_call_recovers(monkeypatch, temporary_files):
    process, launcher, killer = _mock_child(monkeypatch)
    process.wait.side_effect = [subprocess.TimeoutExpired("worker", 1), -9, 0, 0, 0]
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    assert launcher.call_count == 2
    assert killer.call_count == 1
    assert process.wait.call_count == 5


@pytest.mark.parametrize("payload, returncode", [
    (b'{"latex":"x=1"}', 1), (b"", 0), (b"not json", 0), (b"\xff", 0),
    (b"[]", 0), (b"null", 0), (b'{"latex":123}', 0), (b'{"error":"failed"}', 0),
    (b'{"latex":"x=1","extra":true}', 0), (b'{"latex":"a photo"}', 0),
    (json.dumps({"latex": "x=" + "a" * 2000}).encode(), 0), (b" " * 8193, 0),
])
def test_child_error_or_malformed_result_returns_empty(monkeypatch, temporary_files, payload, returncode):
    process, _, killer = _mock_child(monkeypatch, payload, returncode)
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    killer.assert_not_called()
    assert process.wait.call_count == 2


def test_launch_failure_closes_files_and_returns_empty(monkeypatch, temporary_files):
    monkeypatch.setattr(formula_tools.subprocess, "Popen", Mock(side_effect=OSError("cannot launch")))
    assert formula_tools.extract_latex_from_image(b"crop") == ""


def test_wait_error_still_kills_and_reaps(monkeypatch, temporary_files):
    process, _, killer = _mock_child(monkeypatch)
    process.wait.side_effect = [OSError("wait failed"), -9]
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    killer.assert_not_called()
    assert process.wait.call_count == 2


def test_already_exited_group_still_reaps_worker(monkeypatch, temporary_files):
    process, _, killer = _mock_child(monkeypatch)
    killer.side_effect = ProcessLookupError
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    killer.assert_not_called()
    assert process.wait.call_count == 2


def test_temporary_storage_error_does_not_launch_worker(monkeypatch):
    monkeypatch.setattr(formula_tools.tempfile, "TemporaryFile", Mock(side_effect=OSError("storage unavailable")))
    launch = Mock()
    monkeypatch.setattr(formula_tools.subprocess, "Popen", launch)
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    launch.assert_not_called()


def test_empty_image_does_not_launch_worker(monkeypatch):
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(formula_tools.subprocess, "Popen", launch)
    assert formula_tools.extract_latex_from_image(b"") == ""
    launch.assert_not_called()


def test_unsupported_platform_does_not_launch_worker(monkeypatch):
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(formula_tools.subprocess, "Popen", launch)
    monkeypatch.delattr(formula_tools.os, "killpg")
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    launch.assert_not_called()


def _local_child(monkeypatch, body):
    original = subprocess.Popen
    processes = []
    prefix = "import os, sys; assert not any(n.startswith('docling') for n in sys.modules); "
    monkeypatch.setattr(formula_tools, "_codeformula_command", lambda fd: [sys.executable, "-c", prefix + body, str(fd)])

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(formula_tools.subprocess, "Popen", launch)
    return processes


def _assert_reaped(process):
    assert process.returncode is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)


def test_local_child_timeout_cleanup_and_recovery(monkeypatch, temporary_files):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "1")
    processes = _local_child(monkeypatch, "import threading; threading.Event().wait()")
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    assert processes[0].returncode == -signal.SIGKILL
    _assert_reaped(processes[0])

    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "10")
    monkeypatch.setattr(formula_tools, "_codeformula_command", lambda fd: [
        sys.executable, "-c",
        "import os,sys; assert sys.stdin.buffer.read() == b'crop'; os.write(int(sys.argv[1]), b'{\"latex\":\"x=1\"}')",
        str(fd),
    ])
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    _assert_reaped(processes[1])


@pytest.mark.parametrize("body, expected", [
    ("assert sys.stdin.buffer.read() == b'crop'; os.write(int(sys.argv[1]), b'{\"latex\":\"x=1\"}')", "x=1"),
    ("sys.exit(2)", ""),
    ("raise RuntimeError('child failure')", ""),
    ("os.write(int(sys.argv[1]), b'broken')", ""),
    ("os.write(int(sys.argv[1]), b' ' * 8193)", ""),
    ("os.write(1, b'x' * 1048576); os.write(2, b'x' * 1048576); os.write(int(sys.argv[1]), b'{\"latex\":\"x=1\"}')", "x=1"),
])
def test_local_child_protocol_and_discarded_output(monkeypatch, temporary_files, body, expected):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "10")
    processes = _local_child(monkeypatch, body)
    assert formula_tools.extract_latex_from_image(b"crop") == expected
    _assert_reaped(processes[0])


def test_local_descendant_with_inherited_streams_does_not_hold_return(monkeypatch, temporary_files):
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "10")
    processes = _local_child(monkeypatch,
        "import subprocess; "
        "subprocess.Popen([sys.executable, '-c', 'import threading; threading.Event().wait()'], "
        "close_fds=False); os.write(int(sys.argv[1]), b'{\"latex\":\"x=1\"}')")
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    _assert_reaped(processes[0])


@pytest.mark.parametrize("latex, expected_code", [
    ("x=1", 0), ("", 0), ("x=" + "𝑥" * 1998, 0),
    ("x=" + "a" * 2000, 1), ("\x00" * 2000, 1), (None, 1),
])
def test_worker_main_bounded_protocol_without_docling(monkeypatch, temporary_files, latex, expected_code):
    from backend.tools import formula_worker

    recognize = Mock(return_value=latex)
    monkeypatch.setattr(formula_worker, "_recognize", recognize)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"crop")))
    with formula_tools.tempfile.TemporaryFile() as result:
        monkeypatch.setattr(sys, "argv", ["formula_worker", str(os.dup(result.fileno()))])
        assert formula_worker.main() == expected_code
        result.seek(0)
        payload = result.read()
    recognize.assert_called_once_with(b"crop")
    if expected_code == 0:
        assert json.loads(payload) == {"latex": latex}
    else:
        assert payload == b""


def test_worker_model_loading_error_is_nonzero(monkeypatch, temporary_files):
    from backend.tools import formula_worker

    monkeypatch.setattr(formula_worker, "_recognize", Mock(side_effect=ImportError("Docling absent")))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"crop")))
    with formula_tools.tempfile.TemporaryFile() as result:
        monkeypatch.setattr(sys, "argv", ["formula_worker", str(os.dup(result.fileno()))])
        assert formula_worker.main() == 1
        result.seek(0)
        assert result.read() == b""


@pytest.mark.parametrize("output", ["  x=1  ", None])
def test_worker_recognizer_preserves_model_and_generation_options(monkeypatch, output):
    import builtins

    from backend.tools import formula_worker

    source = MagicMock()
    source.__enter__.return_value = source
    image = MagicMock()
    source.convert.return_value = image
    pil_image = Mock()
    pil_image.open.return_value = source
    options = Mock()
    pipeline = Mock(return_value=SimpleNamespace(code_formula_options=options))
    accelerator = Mock()
    engine_input = Mock()
    model = Mock()
    if output is None:
        model.engine = None
    else:
        model.engine.predict_batch.return_value = [SimpleNamespace(text=output)]
        model._post_process.return_value = [output]
    model_class = Mock(return_value=model)
    modules = {
        "PIL": SimpleNamespace(Image=pil_image),
        "docling.datamodel.accelerator_options": SimpleNamespace(AcceleratorOptions=accelerator),
        "docling.datamodel.pipeline_options": SimpleNamespace(PdfPipelineOptions=pipeline),
        "docling.models.inference_engines.vlm": SimpleNamespace(VlmEngineInput=engine_input),
        "docling.models.stages.code_formula.code_formula_vlm_model": SimpleNamespace(CodeFormulaVlmModel=model_class),
    }
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in modules:
            return modules[name]
        if name.startswith("docling"):
            pytest.fail("Unexpected real Docling import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert formula_worker._recognize(b"crop") == ("x=1" if output else "")
    options.model_copy.assert_called_once_with(update={"extract_code": False, "extract_formulas": True})
    model_class.assert_called_once_with(
        enabled=True, enable_remote_services=False, artifacts_path=None,
        options=options.model_copy.return_value, accelerator_options=accelerator.return_value,
    )
    if output is None:
        engine_input.assert_not_called()
        pil_image.open.assert_not_called()
    else:
        assert pil_image.open.call_args.args[0].getvalue() == b"crop"
        source.convert.assert_called_once_with("RGB")
        engine_input.assert_called_once_with(
            image=image, prompt="<formula>", temperature=0.0, max_new_tokens=512,
            extra_generation_config={"skip_special_tokens": False},
        )
        model.engine.predict_batch.assert_called_once_with([engine_input.return_value])
        model._post_process.assert_called_once_with([output])
        source.__exit__.assert_called_once()
        image.__exit__.assert_called_once()


# ── Testes de regressão ──


def test_killpg_nao_chamado_em_sucesso(monkeypatch, temporary_files):
    """Regressão M2: os.killpg NÃO deve ser chamado quando o processo termina normalmente."""
    process, _, killer = _mock_child(monkeypatch)
    assert formula_tools.extract_latex_from_image(b"crop") == "x=1"
    killer.assert_not_called()


def test_killpg_chamado_em_timeout(monkeypatch, temporary_files):
    """Regressão M2: os.killpg DEVE ser chamado quando o processo excede o orçamento."""
    monkeypatch.setenv("FORMULA_CODEFORMULA_TIMEOUT", "0.01")
    process, _, killer = _mock_child(monkeypatch)
    process.wait.side_effect = subprocess.TimeoutExpired("worker", 0.01)
    assert formula_tools.extract_latex_from_image(b"crop") == ""
    killer.assert_called_once_with(process.pid, signal.SIGKILL)


def test_get_ocr_lock_prevents_duplicate_instantiation(monkeypatch):
    """Regressão M1: _get_ocr com lock não cria duas instâncias."""
    from backend.tools import formula_tools

    calls = []
    original_rapidocr = None
    try:
        from rapidocr import RapidOCR
        original_rapidocr = RapidOCR
    except ImportError:
        pass

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            calls.append(1)

    monkeypatch.setattr(formula_tools, "_ocr_engine", None)
    monkeypatch.setattr(formula_tools, "_ocr_failed", False)
    if original_rapidocr:
        monkeypatch.setattr("rapidocr.RapidOCR", FakeRapidOCR)
        monkeypatch.setattr("rapidocr.EngineType", type("ET", (), {"TORCH": "torch"}))

    import threading
    barrier = threading.Barrier(5)
    results = []

    def call_ocr():
        barrier.wait()
        results.append(formula_tools._get_ocr())

    threads = [threading.Thread(target=call_ocr) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    if original_rapidocr:
        assert len(calls) == 1, f"RapidOCR instanciado {len(calls)} vezes (esperado 1)"
    assert all(r is results[0] for r in results)