"""The pinned generation inputs are complete, reproducible public files."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def capture_module():
    spec = importlib.util.spec_from_file_location(
        "capture", ROOT / "scripts/capture_toolbox_contract.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pinned_files_match_provenance():
    directory = ROOT / "tests/fixtures"
    manifest = json.loads((directory / "toolbox-snapshot.json").read_text())
    assert len(manifest["commit"]) == 40
    assert set(manifest["sha256"]) == {"toolbox-contract.json"} | {
        f"toolbox-schemas/{name}" for name in capture_module().SDK_MODEL_SCHEMAS
    }
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    contract = json.loads((directory / "toolbox-contract.json").read_text())
    assert len(contract["dataset_routes"]) == 8
    assert contract["schema_refs"]


def test_capture_failure_preserves_previous_inputs(monkeypatch, tmp_path):
    capture = capture_module()
    target = tmp_path / "toolbox-contract.json"
    target.write_text("previous")

    def fetch(url, **kwargs):
        if "contract/" in url:
            return json.dumps(
                dict(capabilities=[], providers=[], dataset_routes=[], schema_refs=[])
            ).encode()
        raise ValueError("incomplete download")

    monkeypatch.setattr(capture, "_fetch_bytes", fetch)
    with pytest.raises(ValueError, match="incomplete"):
        capture.write_snapshot("a" * 40, target)
    assert target.read_text() == "previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["toolbox-contract.json"]


def test_capture_rejects_mutable_refs_before_download(monkeypatch):
    capture = capture_module()
    monkeypatch.setattr(
        capture, "_fetch_bytes", lambda *a, **k: pytest.fail("network called")
    )
    with pytest.raises(ValueError, match="immutable"):
        capture.snapshot("develop")


def test_public_download_never_sends_deployment_api_key(monkeypatch):
    capture = capture_module()
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b"{}"

    monkeypatch.setenv("TOOLBOX_API_KEY", "deployment-secret")
    monkeypatch.setattr(
        capture.urllib.request,
        "urlopen",
        lambda request, **k: (seen.append(request), Response())[1],
    )
    capture._fetch_bytes("https://raw.githubusercontent.com/example")
    capture._fetch("http://localhost/v1/providers")
    assert not seen[0].has_header("Authorization")
    assert seen[1].get_header("Authorization") == "Bearer deployment-secret"


def test_custom_output_name_is_recorded_in_checksum_manifest(monkeypatch, tmp_path):
    capture = capture_module()
    raw = b'{"capabilities":[],"providers":[],"dataset_routes":[],"schema_refs":[]}'
    manifest = {
        "commit": "a" * 40,
        "sha256": {"toolbox-contract.json": hashlib.sha256(raw).hexdigest()},
    }
    monkeypatch.setattr(
        capture,
        "snapshot",
        lambda ref: {
            "toolbox-contract.json": raw,
            "toolbox-snapshot.json": json.dumps(manifest).encode(),
        },
    )
    capture.write_snapshot("a" * 40, tmp_path / "custom.json")
    recorded = json.loads((tmp_path / "toolbox-snapshot.json").read_text())
    assert recorded["sha256"] == {"custom.json": hashlib.sha256(raw).hexdigest()}
    assert (tmp_path / "custom.json").read_bytes() == raw


@pytest.mark.parametrize("name", ["toolbox-snapshot.json", "toolbox-schemas"])
def test_output_cannot_overwrite_metadata_paths(monkeypatch, tmp_path, name):
    capture = capture_module()
    monkeypatch.setattr(
        capture, "snapshot", lambda ref: pytest.fail("download started")
    )
    with pytest.raises(ValueError, match="metadata path"):
        capture.write_snapshot("a" * 40, tmp_path / name)
    assert not list(tmp_path.iterdir())


@pytest.fixture
def diagnostic_capture(monkeypatch, tmp_path):
    capture = capture_module()
    fixtures = tmp_path / "fixtures"
    schemas = fixtures / "toolbox-schemas"
    schemas.mkdir(parents=True)
    paths = [
        fixtures / "toolbox-contract.json",
        fixtures / "toolbox-snapshot.json",
        schemas / "latex@1.json",
    ]
    for path in paths:
        path.write_bytes(b"previous generation input")
    monkeypatch.setattr(capture, "DEFAULT_OUT", paths[0])
    return capture, fixtures, {path: path.read_bytes() for path in paths}


@pytest.mark.parametrize(
    "relative",
    [
        "toolbox-contract.json",
        "toolbox-snapshot.json",
        "toolbox-schemas/latex@1.json",
        "toolbox-schemas/new-schema.json",
        "diagnostics/new-live.json",
    ],
)
def test_live_capture_cannot_overwrite_any_fixture(
    monkeypatch, diagnostic_capture, relative, capsys
):
    capture, fixtures, previous = diagnostic_capture
    monkeypatch.setattr(
        capture, "build", lambda url: pytest.fail("live download started")
    )
    target = fixtures / relative
    with pytest.raises(SystemExit) as error:
        capture.main(["--url", "http://toolbox", "--out", str(target)])
    assert error.value.code == 2
    assert "outside tests/fixtures" in capsys.readouterr().err
    assert {
        path: path.read_bytes() for path in fixtures.rglob("*") if path.is_file()
    } == previous


@pytest.mark.parametrize(
    "target",
    ["toolbox-snapshot.json", "toolbox-schemas/latex@1.json", "toolbox-schemas"],
)
def test_live_capture_rejects_symlink_aliases(
    monkeypatch, diagnostic_capture, tmp_path, target
):
    capture, fixtures, previous = diagnostic_capture
    alias = tmp_path / "outside-link"
    alias.symlink_to(fixtures / target)
    output = alias / "new.json" if alias.is_dir() else alias
    monkeypatch.setattr(
        capture, "build", lambda url: pytest.fail("live download started")
    )
    with pytest.raises(SystemExit) as error:
        capture.main(["--url", "http://toolbox", "--out", str(output)])
    assert error.value.code == 2
    assert {
        path: path.read_bytes() for path in fixtures.rglob("*") if path.is_file()
    } == previous


def test_live_capture_outside_fixtures_keeps_pinned_inputs(
    monkeypatch, diagnostic_capture, tmp_path
):
    capture, fixtures, previous = diagnostic_capture
    calls = []
    payload = {"capabilities": [], "providers": []}

    def build(url):
        calls.append(url)
        return payload

    monkeypatch.setattr(capture, "build", build)
    target = tmp_path / "diagnostics" / "live.json"
    assert capture.main(["--url", "http://toolbox", "--out", str(target)]) == 0
    assert json.loads(target.read_text()) == payload
    assert calls == ["http://toolbox"]
    assert {
        path: path.read_bytes() for path in fixtures.rglob("*") if path.is_file()
    } == previous


@pytest.mark.parametrize("contract", [[], None, "contract", 42, True])
def test_non_object_contract_is_a_cli_error_without_partial_writes(
    monkeypatch, tmp_path, capsys, contract
):
    capture = capture_module()
    paths = [
        tmp_path / "toolbox-contract.json",
        tmp_path / "toolbox-snapshot.json",
        tmp_path / "toolbox-schemas" / "reference@1.json",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"previous generation input")
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return json.dumps(contract).encode()

    monkeypatch.setattr(capture, "_fetch_bytes", fetch)
    with pytest.raises(SystemExit) as error:
        capture.main(["--ref", "a" * 40, "--out", str(paths[0])])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "must be a JSON object" in message and "Traceback" not in message
    assert len(calls) == 1
    assert all(path.read_bytes() == b"previous generation input" for path in paths)
