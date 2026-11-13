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
from acessilia_sdk.toolbox.clients.dataset import ToolboxDatasetClient

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
    assert set(request.extensions["timeout"].values()) == {cli.CATALOG_TIMEOUT_SECONDS}
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


# run


EXECUTE = f"{A}/v1/capabilities/media.inspect:execute"
ENVELOPE = {
    "status": "succeeded",
    "capability": "media.inspect",
    "provider": "pure-media-inspect",
    "document": {"media_type": "application/pdf", "page_count": 2},
}


def _form(request: httpx.Request) -> str:
    return request.content.decode("utf-8", errors="replace")


def _field(name: str, value: str) -> str:
    return f'name="{name}"\r\n\r\n{value}\r\n'


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "source.pdf"
    path.write_bytes(CONTENT)
    return path


def test_run_calls_an_execute_capability_and_prints_its_envelope(pdf, key_file) -> None:
    with respx.mock() as router:
        route = router.post(EXECUTE).mock(return_value=httpx.Response(200, json=ENVELOPE))
        status, out, err = _run(
            "--endpoint", A, "--api-key-file", str(key_file),
            "run", "media.inspect", "--file", str(pdf),
        )

    assert (status, err) == (0, "")
    assert json.loads(out) == ENVELOPE
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-key"
    body = _form(request)
    # The registry's provider and contract version, and the file itself.
    assert _field("provider", "pure-media-inspect") in body
    assert _field("version", "1") in body
    assert 'filename="source.pdf"' in body and "application/pdf" in body
    # The clients' own timeout, not the catalogue's 10 s.
    assert set(request.extensions["timeout"].values()) == {3600}


def test_run_forwards_the_provider_language_parameters_and_cache_choice(pdf) -> None:
    with respx.mock() as router:
        route = router.post(f"{A}/v1/capabilities/pdf.render:execute").mock(
            return_value=httpx.Response(200, json={**ENVELOPE, "capability": "pdf.render"})
        )
        status, _, err = _run(
            "--endpoint", A, "--timeout", "30",
            "run", "pdf.render", "--file", str(pdf),
            "--provider", "other-pdf", "--language", "en",
            "--parameters", '{"page_number": 2, "max_side": 512}', "--no-cache",
        )

    assert (status, err) == (0, "")
    request = route.calls.last.request
    body = _form(request)
    assert _field("provider", "other-pdf") in body
    assert _field("language", "en") in body
    assert _field("version", "2") in body
    assert json.loads(body.split('name="parameters"\r\n\r\n', 1)[1].split("\r\n", 1)[0]) == {
        "page_number": 2, "max_side": 512,
    }
    assert 'name="no_cache"' in body
    assert set(request.extensions["timeout"].values()) == {30.0}


def test_a_formula_in_a_txt_file_goes_as_plain_text_to_the_math_provider(tmp_path) -> None:
    """The README's math.verbalize example: the same media type the math client sends."""
    formula = tmp_path / "formula.txt"
    formula.write_text(r"\frac{a}{b}", encoding="utf-8")
    with respx.mock() as router:
        route = router.post(f"{A}/v1/capabilities/math.verbalize:execute").mock(
            return_value=httpx.Response(
                200, json={**ENVELOPE, "capability": "math.verbalize", "document": {}}
            )
        )
        status, _, err = _run(
            "--endpoint", A, "run", "math.verbalize", "--file", str(formula), "--language", "pt-BR"
        )

    assert (status, err) == (0, "")
    body = _form(route.calls.last.request)
    assert 'filename="formula.txt"' in body and "Content-Type: text/plain" in body
    assert _field("provider", "math-speech") in body


def test_run_with_a_stored_artifact_sends_its_id_and_no_file() -> None:
    with respx.mock() as router:
        route = router.post(EXECUTE).mock(return_value=httpx.Response(200, json=ENVELOPE))
        status, _, _ = _run("--endpoint", A, "run", "media.inspect", "--artifact", ARTIFACT_ID)

    assert status == 0
    body = _form(route.calls.last.request)
    assert f"artifact_id={ARTIFACT_ID.replace(':', '%3A')}" in body
    assert "filename=" not in body


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401, json={"detail": "no key"}), "ToolboxAuthenticationError"),
        (httpx.Response(200, json={**ENVELOPE, "status": "failed"}), "ToolboxContractViolation"),
        (httpx.ReadTimeout("slow"), "ToolboxTimeout"),
    ],
    ids=["401", "failed-envelope", "timeout"],
)
def test_a_failed_call_is_reported_typed_with_status_1(pdf, response, error) -> None:
    with respx.mock() as router:
        route = router.post(EXECUTE)
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        status, out, err = _run("--endpoint", A, "run", "media.inspect", "--file", str(pdf))

    assert (status, out) == (1, "")
    assert err.startswith(f"error: {error}: ")


def test_run_fails_over_to_a_secondary_that_publishes_the_capability(pdf) -> None:
    with respx.mock() as router:
        router.post(EXECUTE).mock(side_effect=httpx.ConnectError("refused"))
        router.get(f"{B}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=[{"id": "media.inspect", "version": 1}])
        )
        router.get(f"{B}/v1/providers").mock(
            return_value=httpx.Response(
                200, json=[{"id": "pure-media-inspect", "capabilities": ["media.inspect"]}]
            )
        )
        router.post(f"{B}/v1/capabilities/media.inspect:execute").mock(
            return_value=httpx.Response(200, json=ENVELOPE)
        )
        status, out, err = _run(
            "--endpoint", A, "--endpoint", B, "run", "media.inspect", "--file", str(pdf)
        )

    assert status == 0
    assert json.loads(out) == ENVELOPE
    lines = err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"warning: endpoint {A} failed: ToolboxProviderUnavailable: ")


def test_run_closes_its_client_on_success_and_on_failure(pdf, monkeypatch) -> None:
    from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

    closed: list[bool] = []
    original = ToolboxCapabilityClient.close

    async def recording_close(self) -> None:
        await original(self)
        closed.append(True)

    monkeypatch.setattr(ToolboxCapabilityClient, "close", recording_close)
    with respx.mock() as router:
        route = router.post(EXECUTE)
        route.mock(return_value=httpx.Response(200, json=ENVELOPE))
        assert _run("--endpoint", A, "run", "media.inspect", "--file", str(pdf))[0] == 0
        route.mock(side_effect=httpx.ReadTimeout("slow"))
        assert _run("--endpoint", A, "run", "media.inspect", "--file", str(pdf))[0] == 1

    assert closed == [True, True]


def test_run_points_every_rest_capability_to_its_command() -> None:
    from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES

    for capability_id, spec in TOOLBOX_CAPABILITIES.items():
        if spec.transport == "execute":
            assert cli.executable_capability(capability_id) is spec
        else:
            with pytest.raises(ValueError, match="is a REST capability") as raised:
                cli.executable_capability(capability_id)
            assert f"'{cli.REST_COMMANDS[capability_id]}' command" in str(raised.value)


# upload


def test_upload_stores_a_file_and_prints_its_artifact_id(pdf, key_file) -> None:
    with respx.mock() as router:
        route = router.post(f"{A}/v1/artifacts").mock(
            return_value=httpx.Response(201, json={"artifact_id": ARTIFACT_ID})
        )
        status, out, err = _run(
            "--endpoint", A, "--api-key-file", str(key_file), "upload", str(pdf)
        )

    assert (status, out, err) == (0, f"{ARTIFACT_ID}\n", "")
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"


def test_a_failed_upload_is_reported_typed(pdf) -> None:
    with respx.mock() as router:
        router.post(f"{A}/v1/artifacts").mock(return_value=httpx.Response(401))
        status, out, err = _run("--endpoint", A, "upload", str(pdf))

    assert (status, out) == (1, "")
    assert err.startswith("error: ToolboxAuthenticationError: ")


# dataset: one command per dataset.* capability, through ToolboxDatasetClient

DS = f"{A}/v1/datasets"

#: capability -> (command arguments, method, route, expected query, response).
DATASET_ROUTES = {
    "dataset.list": (["list"], "GET", f"{DS}", {}, [{"id": "dr-docbench"}]),
    "dataset.describe": (
        ["describe", "dr-docbench", "--revision", "r1"],
        "GET", f"{DS}/dr-docbench", {"revision": "r1"}, {"id": "dr-docbench"},
    ),
    "dataset.list_splits": (
        ["splits", "dr-docbench"], "GET", f"{DS}/dr-docbench/splits", {}, [{"name": "dev"}],
    ),
    "dataset.list_items": (
        ["items", "dr-docbench", "dev", "--limit", "2", "--offset", "4"],
        "GET", f"{DS}/dr-docbench/splits/dev/items", {"limit": "2", "offset": "4"},
        [{"id": "a"}, {"id": "b"}],
    ),
    "dataset.get_item": (
        ["item", "dr-docbench", "dev", "doc_p1"],
        "GET", f"{DS}/dr-docbench/splits/dev/items/doc_p1", {}, {"id": "doc_p1"},
    ),
    "dataset.sample": (
        ["sample", "dr-docbench", "dev", "--n", "3"],
        "GET", f"{DS}/dr-docbench/splits/dev/sample", {"n": "3"}, [{"id": "a"}],
    ),
    "dataset.sync": (
        ["sync", "dr-docbench", "--split", "dev"],
        "POST", f"{DS}/dr-docbench/sync", {"split": "dev"}, {"synced": 3},
    ),
}


def test_every_rest_capability_of_the_registry_has_a_dispatch_test() -> None:
    """Coverage by transport (#402, step 8): each REST route is exercised here."""
    from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES

    rest = {cid for cid, spec in TOOLBOX_CAPABILITIES.items() if spec.transport == "rest"}
    exercised = set(DATASET_ROUTES) | {
        "dataset.get_artifact",  # test_dataset_artifact_is_written_to_the_output
        "artifact.store",  # test_upload_stores_a_file_and_prints_its_artifact_id
        "artifact.retrieve",  # test_download_writes_the_verified_artifact
    }
    assert exercised == rest
    assert set(cli.REST_COMMANDS) == rest


@pytest.mark.parametrize("capability_id", sorted(DATASET_ROUTES))
def test_each_dataset_command_calls_its_route(capability_id, key_file) -> None:
    argv, method, url, query, response = DATASET_ROUTES[capability_id]
    with respx.mock() as router:
        route = router.route(method=method, url__startswith=url).mock(
            return_value=httpx.Response(200, json=response)
        )
        status, out, err = _run(
            "--endpoint", A, "--api-key-file", str(key_file), "dataset", *argv
        )

    assert (status, err) == (0, "")
    assert json.loads(out) == response
    request = route.calls.last.request
    assert str(request.url.copy_with(query=None)) == url
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer secret-key"


def test_dataset_items_all_reads_every_page_up_to_the_limit() -> None:
    def page(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        offset = int(request.url.params["offset"])
        size = max(0, min(limit, 2500 - offset))
        return httpx.Response(200, json=[{"id": str(n)} for n in range(offset, offset + size)])

    with respx.mock() as router:
        route = router.get(f"{DS}/dr-docbench/splits/dev/items").mock(side_effect=page)
        status, out, _ = _run(
            "--endpoint", A, "dataset", "items", "dr-docbench", "dev", "--all", "--limit", "1500"
        )

    assert status == 0
    assert len(json.loads(out)) == 1500
    assert [
        (call.request.url.params["limit"], call.request.url.params["offset"])
        for call in route.calls
    ] == [("1000", "0"), ("500", "1000")]


def test_dataset_artifact_is_written_to_the_output(tmp_path) -> None:
    output = tmp_path / "page_1.jpg"
    url = f"{DS}/dr-docbench/splits/dev/items/doc_p1/artifacts/images/page%201.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=b"jpeg"))
        status, out, err = _run(
            "--endpoint", A, "dataset", "artifact", "dr-docbench", "dev", "doc_p1",
            "images/page 1.jpg", str(output),
        )

    assert (status, out, err) == (0, f"{output}\n", "")
    assert output.read_bytes() == b"jpeg"
    assert [path.name for path in tmp_path.iterdir()] == ["page_1.jpg"]


def test_a_dataset_failure_is_typed_and_leaves_no_partial_artifact(tmp_path) -> None:
    with respx.mock() as router:
        router.get(f"{DS}/dr-docbench/splits/dev/items/x/artifacts/a.md").mock(
            return_value=httpx.Response(404, json={"detail": "no such artifact"})
        )
        status, out, err = _run(
            "--endpoint", A, "dataset", "artifact", "dr-docbench", "dev", "x", "a.md",
            str(tmp_path / "a.md"),
        )

    assert (status, out) == (1, "")
    assert err.startswith("error: ToolboxArtifactNotFound: ")
    assert list(tmp_path.iterdir()) == []


def test_dataset_sample_is_not_repeated_on_another_endpoint() -> None:
    """dataset.sample is not idempotent (#406): one attempt, no failover."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{DS}/dr-docbench/splits/dev/sample").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        other = router.get(f"{B}/v1/datasets/dr-docbench/splits/dev/sample")
        status, _, err = _run(
            "--endpoint", A, "--endpoint", B, "dataset", "sample", "dr-docbench", "dev"
        )

    assert status == 1
    assert err.startswith("error: ToolboxTimeout: ")
    assert not other.called


def test_dataset_commands_close_their_client(monkeypatch) -> None:
    closed: list[bool] = []
    original = ToolboxDatasetClient.close

    async def recording_close(self) -> None:
        await original(self)
        closed.append(True)

    monkeypatch.setattr(ToolboxDatasetClient, "close", recording_close)
    with respx.mock() as router:
        route = router.get(DS)
        route.mock(return_value=httpx.Response(200, json=[]))
        assert _run("--endpoint", A, "dataset", "list")[0] == 0
        route.mock(side_effect=httpx.ConnectError("refused"))
        assert _run("--endpoint", A, "dataset", "list")[0] == 1

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
        ["--endpoint", A, "run", "no.such.capability", "--artifact", ARTIFACT_ID],
        ["--endpoint", A, "run", "artifact.retrieve", "--artifact", ARTIFACT_ID],
        ["--endpoint", A, "run", "dataset.list", "--artifact", ARTIFACT_ID],
        ["--endpoint", A, "run", "media.inspect", "--artifact", "not-an-id"],
        ["--endpoint", A, "run", "media.inspect", "--file", "/no/such/file.pdf"],
        ["--endpoint", A, "run", "media.inspect", "--artifact", ARTIFACT_ID, "--parameters", "{"],
        ["--endpoint", A, "run", "media.inspect", "--artifact", ARTIFACT_ID, "--parameters", "[1]"],
        ["--endpoint", A, "upload", "/no/such/file.pdf"],
        ["--endpoint", A, "dataset", "items", "d", "dev", "--all", "--offset", "5"],
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
        "run-unknown-capability",
        "run-rest-artifact",
        "run-rest-dataset",
        "run-bad-artifact",
        "run-missing-file",
        "run-bad-json",
        "run-json-not-object",
        "upload-missing-file",
        "dataset-all-with-offset",
    ],
)
def test_invalid_arguments_exit_2_without_a_request(argv) -> None:
    with respx.mock() as router:
        status, out, err = _run(*argv)
        assert not router.calls

    assert (status, out) == (2, "")
    assert err.startswith("error: ")


def test_run_needs_exactly_one_input() -> None:
    for extra in ([], ["--file", "a.pdf", "--artifact", ARTIFACT_ID]):
        with pytest.raises(SystemExit) as raised:
            cli.main(["--endpoint", A, "run", "media.inspect", *extra], stderr=io.StringIO())
        assert raised.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["dataset"],
        ["dataset", "items", "d"],
        ["dataset", "items", "d", "dev", "--limit", "-1"],
        ["dataset", "sample", "d", "dev", "--n", "0"],
    ],
    ids=["no-route", "no-split", "negative-limit", "zero-sample"],
)
def test_dataset_argument_errors_exit_2(argv) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--endpoint", A, *argv], stderr=io.StringIO())
    assert raised.value.code == 2


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
    """The endpoint check rejects it before any request, with no traceback."""
    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED % str(SRC), "--endpoint", "http://toolbox.test:bad", "catalog"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert result.stderr.startswith(
        "error: Toolbox base_url must have a port between 0 and 65535"
    )
    assert "Traceback" not in result.stderr
