"""``python -m acessilia_sdk``: the catalogue and verified downloads, without the core."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk import cli
from acessilia_sdk.toolbox.clients.artifact import ToolboxArtifactClient

A = "http://toolbox-a.test"
B = "http://toolbox-b.test"
SRC = Path(__file__).resolve().parents[1] / "src"
CAPABILITIES = [
    {"id": "document.structure.extract", "version": 1},
    {"id": "math.recognize", "version": 1},
]
PROVIDERS = [
    {"id": "docling", "capabilities": ["document.structure.extract"]},
    {"id": "pp-formulanet", "capabilities": ["math.recognize"]},
]
CONTENT = b"%PDF-1.7 accessible\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
ARTIFACT_ID = f"sha256:{DIGEST}"


def _run(*argv: str, stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    status = cli.main(list(argv), stdin=io.StringIO(stdin), stdout=out, stderr=err)
    return status, out.getvalue(), err.getvalue()


def _serve_catalog(router: respx.MockRouter, base_url: str = A) -> respx.Route:
    router.get(f"{base_url}/v1/providers").mock(
        return_value=httpx.Response(200, json=PROVIDERS)
    )
    return router.get(f"{base_url}/v1/capabilities").mock(
        return_value=httpx.Response(200, json=CAPABILITIES)
    )


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "key"
    path.write_text("secret-key\n", encoding="utf-8")
    return path


# catalog


def test_catalog_prints_the_first_endpoint_s_catalogue(key_file) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = _serve_catalog(router)
        other = _serve_catalog(router, B)
        status, out, err = _run(
            "--endpoint", A, "--endpoint", B, "--api-key-file", str(key_file), "catalog"
        )

    assert (status, err) == (0, "")
    document = json.loads(out)
    assert document["endpoint"] == A
    assert document["capabilities"] == {"document.structure.extract": 1, "math.recognize": 1}
    assert document["providers"] == {
        "docling": ["document.structure.extract"],
        "pp-formulanet": ["math.recognize"],
    }
    assert len(document["revision"]) == 16
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert set(request.extensions["timeout"].values()) == {cli.DEFAULT_TIMEOUT_SECONDS}
    assert not other.called


def test_the_key_can_come_from_standard_input_and_the_timeout_from_an_argument() -> None:
    with respx.mock() as router:
        route = _serve_catalog(router)
        status, _, _ = _run(
            "--endpoint", A, "--api-key-file", "-", "--timeout", "3", "catalog",
            stdin="piped-key\n",
        )

    assert status == 0
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer piped-key"
    assert set(request.extensions["timeout"].values()) == {3.0}


def test_without_a_key_file_no_key_is_sent() -> None:
    with respx.mock() as router:
        route = _serve_catalog(router)
        assert _run("--endpoint", A, "catalog")[0] == 0
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (httpx.ReadTimeout("slow"), "ToolboxTimeout"),
        (httpx.ConnectError("refused"), "ToolboxProviderUnavailable"),
        (httpx.Response(401), "ToolboxAuthenticationError"),
        (httpx.Response(200, text="not json"), "ToolboxContractViolation"),
    ],
    ids=["timeout", "unreachable", "401", "invalid-json"],
)
def test_a_catalogue_failure_is_reported_typed_with_status_1(failure, error) -> None:
    with respx.mock() as router:
        route = router.get(f"{A}/v1/capabilities")
        if isinstance(failure, Exception):
            route.mock(side_effect=failure)
        else:
            route.mock(return_value=failure)
        status, out, err = _run("--endpoint", A, "catalog")

    assert (status, out) == (1, "")
    assert err.startswith(f"error: {error}: ")


# download


def test_download_writes_the_verified_artifact(tmp_path, key_file) -> None:
    output = tmp_path / "out.pdf"
    with respx.mock() as router:
        route = router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            return_value=httpx.Response(200, content=CONTENT)
        )
        status, out, err = _run(
            "--endpoint", A, "--api-key-file", str(key_file), "download", ARTIFACT_ID, str(output)
        )

    assert (status, out, err) == (0, f"{output}\n", "")
    assert output.read_bytes() == CONTENT
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"


def _publish_retrieve(router: respx.MockRouter, base_url: str) -> None:
    """A secondary is used only if its catalogue publishes the capability."""
    router.get(f"{base_url}/v1/capabilities").mock(
        return_value=httpx.Response(200, json=[{"id": "artifact.retrieve", "version": 1}])
    )
    router.get(f"{base_url}/v1/providers").mock(return_value=httpx.Response(200, json=[]))


def test_download_moves_on_when_an_endpoint_does_not_have_the_artifact(tmp_path) -> None:
    output = tmp_path / "out.pdf"
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{DIGEST}").mock(return_value=httpx.Response(404))
        _publish_retrieve(router, B)
        router.get(f"{B}/v1/artifacts/{DIGEST}").mock(
            return_value=httpx.Response(200, content=CONTENT)
        )
        status, out, err = _run(
            "--endpoint", A, "--endpoint", B, "download", DIGEST, str(output)
        )

    assert (status, out) == (0, f"{output}\n")
    assert output.read_bytes() == CONTENT
    # The switch to another deployment is visible (ADR-0006, ADR-0014).
    lines = err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"warning: endpoint {A} failed: ToolboxArtifactNotFound: ")


def test_a_timeout_on_the_primary_is_reported_when_the_secondary_succeeds(tmp_path) -> None:
    output = tmp_path / "out.pdf"
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        _publish_retrieve(router, B)
        router.get(f"{B}/v1/artifacts/{ARTIFACT_ID}").mock(
            return_value=httpx.Response(200, content=CONTENT)
        )
        status, out, err = _run(
            "--endpoint", A, "--endpoint", B, "download", ARTIFACT_ID, str(output)
        )

    assert (status, out) == (0, f"{output}\n")
    assert output.read_bytes() == CONTENT
    lines = err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"warning: endpoint {A} failed: ToolboxTimeout: ")


def test_when_every_endpoint_fails_each_is_reported_then_the_error(tmp_path) -> None:
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            side_effect=httpx.ConnectError("refused")
        )
        _publish_retrieve(router, B)
        router.get(f"{B}/v1/artifacts/{ARTIFACT_ID}").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        status, out, err = _run(
            "--endpoint", A, "--endpoint", B, "download", ARTIFACT_ID, str(tmp_path / "x")
        )

    assert (status, out) == (1, "")
    lines = err.splitlines()
    assert lines[0].startswith(f"warning: endpoint {A} failed: ToolboxProviderUnavailable: ")
    assert lines[1].startswith(f"warning: endpoint {B} failed: ToolboxTimeout: ")
    assert lines[2].startswith("error: ToolboxUnavailable: ")
    assert len(lines) == 3


def test_one_endpoint_reports_its_error_without_a_failover_line(tmp_path) -> None:
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        status, _, err = _run("--endpoint", A, "download", ARTIFACT_ID, str(tmp_path / "x"))

    assert status == 1
    assert [line.split(":", 1)[0] for line in err.splitlines()] == ["error"]


def test_a_digest_mismatch_fails_and_leaves_no_file(tmp_path) -> None:
    output = tmp_path / "out.pdf"
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            return_value=httpx.Response(200, content=b"something else")
        )
        status, out, err = _run("--endpoint", A, "download", ARTIFACT_ID, str(output))

    assert (status, out) == (1, "")
    assert err.startswith("error: ToolboxContractViolation: ")
    assert list(tmp_path.iterdir()) == []


def test_a_missing_output_directory_is_a_file_system_error(tmp_path) -> None:
    output = tmp_path / "missing" / "out.pdf"
    with respx.mock() as router:
        router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}").mock(
            return_value=httpx.Response(200, content=CONTENT)
        )
        status, _, err = _run("--endpoint", A, "download", ARTIFACT_ID, str(output))

    assert status == 1
    assert err.startswith("error: FileNotFoundError: ")


def test_download_closes_its_client_on_success_and_on_failure(tmp_path, monkeypatch) -> None:
    closed: list[bool] = []
    original = ToolboxArtifactClient.close

    async def recording_close(self) -> None:
        await original(self)
        closed.append(True)

    monkeypatch.setattr(ToolboxArtifactClient, "close", recording_close)
    with respx.mock() as router:
        route = router.get(f"{A}/v1/artifacts/{ARTIFACT_ID}")
        route.mock(return_value=httpx.Response(200, content=CONTENT))
        assert _run("--endpoint", A, "download", ARTIFACT_ID, str(tmp_path / "a"))[0] == 0
        route.mock(side_effect=httpx.ReadTimeout("slow"))
        assert _run("--endpoint", A, "download", ARTIFACT_ID, str(tmp_path / "b"))[0] == 1

    assert closed == [True, True]


# arguments


@pytest.mark.parametrize(
    "argv",
    [
        ["--endpoint", "not-a-url", "catalog"],
        ["--endpoint", "http://toolbox.test:bad", "catalog"],
        ["--endpoint", "http://toolbox.test:bad", "download", ARTIFACT_ID, "out"],
        ["--endpoint", A, "--endpoint", "http://toolbox-b.test:99999", "catalog"],
        ["--endpoint", A, "--endpoint", "ftp://toolbox-b.test", "download", ARTIFACT_ID, "out"],
        ["--endpoint", A, "--timeout", "0", "catalog"],
        ["--endpoint", A, "download", "not-an-id", "out"],
        ["--endpoint", A, "download", "a" * 64 + "\n", "out"],
        ["--endpoint", A, "download", ARTIFACT_ID + " ", "out"],
    ],
    ids=[
        "no-scheme",
        "bad-port-catalog",
        "bad-port-download",
        "bad-secondary-port",
        "bad-secondary-scheme",
        "bad-timeout",
        "bad-id",
        "id-with-trailing-newline",
        "id-with-trailing-space",
    ],
)
def test_invalid_arguments_exit_2_without_a_request(argv) -> None:
    with respx.mock() as router:
        status, out, err = _run(*argv)
        assert not router.calls

    assert (status, out) == (2, "")
    assert err.startswith("error: ")


def test_an_endpoint_is_required() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["catalog"], stderr=io.StringIO())
    assert raised.value.code == 2


# Isolation: the command line runs on the SDK alone (#402 acceptance).

_BLOCKED = """
import runpy, sys

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("backend", "acessilia_toolbox"):
            raise ImportError(f"blocked: {name}")
        return None

sys.meta_path.insert(0, _Block())
sys.path.insert(0, %r)
sys.argv = ["acessilia_sdk"] + sys.argv[1:]
runpy.run_module("acessilia_sdk", run_name="__main__")
"""


def test_python_m_acessilia_sdk_runs_with_the_core_blocked() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED % str(SRC), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "catalog" in result.stdout and "download" in result.stdout


def test_an_unreachable_toolbox_is_typed_in_a_fresh_interpreter() -> None:
    """A real socket error, end to end, with the core blocked."""
    result = subprocess.run(
        [
            sys.executable, "-c", _BLOCKED % str(SRC),
            "--endpoint", "http://127.0.0.1:9", "--timeout", "2", "catalog",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("error: ToolboxProviderUnavailable: ")


def test_an_invalid_port_is_a_usage_error_from_the_command_line_too() -> None:
    """Before #437's review this ended in an httpx.InvalidURL traceback, exit 1."""
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED % str(SRC), "--endpoint", "http://toolbox.test:bad", "catalog"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert result.stderr.startswith("error: unusable endpoint 'http://toolbox.test:bad'")
    assert "Traceback" not in result.stderr
