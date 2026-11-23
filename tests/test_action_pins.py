"""The action-pin check separates commit SHAs from tag objects (#812)."""

from __future__ import annotations

import urllib.error
from pathlib import Path

import yaml

from scripts import check_action_pins as check

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "33d7b85da1a04171e211befe2c739303b9a4c066"
TAG_OBJECT = "5895b2c9be147bc7f1c75ce72c5cb577febb1907"


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _commit_response(request: object, timeout: float) -> _Response:
    return _Response()


def _missing_response(request: object, timeout: float) -> _Response:
    raise urllib.error.HTTPError(str(request), 404, "Not Found", {}, None)


def _unexpected_request(request: object, timeout: float) -> _Response:
    raise AssertionError("a floating ref must not reach the API")


def test_iter_uses_skips_local_and_docker_actions(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/test.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + COMMIT + "\n"
        "      - uses: ./.github/actions/setup-root\n"
        "      - uses: docker://alpine:3\n",
        encoding="utf-8",
    )

    references = list(check.iter_uses(tmp_path))

    assert references == [(workflow, 4, f"actions/checkout@{COMMIT}")]


def test_parse_action_pin_keeps_only_the_repository() -> None:
    pin = check.parse_action_pin(
        f"github/codeql-action/init@{COMMIT}",
        path=Path(".github/workflows/codeql.yml"),
        line=39,
    )

    assert pin.repository == "github/codeql-action"
    assert pin.ref == COMMIT


def test_parse_action_pin_keeps_a_floating_ref_for_the_problem_check() -> None:
    pin = check.parse_action_pin(
        "actions/checkout@v4", path=Path("workflow.yml"), line=1
    )

    assert pin.ref == "v4"


def test_a_commit_pin_passes() -> None:
    pin = check.ActionPin(Path("workflow.yml"), 1, "actions/checkout", COMMIT)

    assert check.pin_problem(
        pin,
        token=None,
        opener=_commit_response,
    ) is None


def test_a_tag_object_pin_is_rejected() -> None:
    pin = check.ActionPin(
        Path("workflow.yml"), 1, "github/codeql-action", TAG_OBJECT
    )

    problem = check.pin_problem(pin, token=None, opener=_missing_response)

    assert problem is not None
    assert "commit object" in problem


def test_a_scoped_token_falls_back_to_the_public_endpoint() -> None:
    calls: list[str | None] = []

    def scoped_404_then_ok(request: object, timeout: float) -> _Response:
        authorization = getattr(request, "get_header", lambda name: None)(
            "Authorization"
        )
        calls.append(authorization)
        if authorization:
            raise urllib.error.HTTPError(str(request), 404, "Not Found", {}, None)
        return _Response()

    assert check.is_commit(
        "actions/checkout",
        COMMIT,
        token="installation-token",
        opener=scoped_404_then_ok,
    )
    assert calls == ["Bearer installation-token", None]


def test_a_floating_pin_is_rejected_without_a_request() -> None:
    pin = check.ActionPin(Path("workflow.yml"), 1, "actions/checkout", "v4")

    problem = check.pin_problem(pin, token=None, opener=_unexpected_request)

    assert problem is not None
    assert "40-character" in problem


def test_repository_action_pins_are_commit_shaped() -> None:
    pins = [
        check.parse_action_pin(reference, path=path, line=line)
        for path, line, reference in check.iter_uses(ROOT)
    ]

    assert pins
    assert all(check.COMMIT_SHA.fullmatch(pin.ref) for pin in pins)


def test_action_pin_check_is_reported_in_prs_and_enforced_on_schedule() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    quality = {step.get("name"): step for step in workflow["jobs"]["quality"]["steps"]}
    report = quality["Report GitHub Action pins"]
    assert "scripts/check_action_pins.py" in report["run"]
    assert "--report-only" in report["run"]
    assert report["env"]["GITHUB_TOKEN"] == "${{ github.token }}"

    scheduled = yaml.safe_load(
        (ROOT / ".github/workflows/scheduled-tests.yml").read_text(encoding="utf-8")
    )
    monitor = {
        step.get("name"): step
        for step in scheduled["jobs"]["monitor"]["steps"]
    }
    strict = monitor["Verify GitHub Action pins"]
    assert "scripts/check_action_pins.py" in strict["run"]
    assert "--report-only" not in strict["run"]
    assert strict["if"] == "always()"
    assert strict["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
