"""The Toolbox's docstruct pin follows the core's release (#470, phase 2, P8)."""

from __future__ import annotations

import hashlib
import urllib.error

import pytest

from scripts import check_docstruct_pin as check

SHA = "a" * 64
RELEASES = ["0.3.0", "0.4.0", "0.5.0"]


def _pyproject(dependency: str) -> str:
    return f'[project]\nname = "toolbox"\ndependencies = [\n  "pydantic>=2",\n  "{dependency}",\n]\n'


def _pin_line(version: str = "0.5.0", sha: str = SHA, repository: str = "A11yDevs/acessilia") -> str:
    return (
        f"acessilia-docstruct @ https://github.com/{repository}/releases/download/"
        f"docstruct-v{version}/acessilia_docstruct-{version}-py3-none-any.whl#sha256={sha}"
    )


def _pin(version: str = "0.5.0", **kwargs) -> check.Pin:
    pin = check.parse_pin(_pyproject(_pin_line(version, **kwargs)))
    assert pin is not None
    return pin


def test_the_pin_is_read_from_the_toolbox_pyproject() -> None:
    pin = _pin("0.5.0")
    assert (pin.repository, pin.tag_version, pin.file_version, pin.sha256) == (
        "A11yDevs/acessilia", "0.5.0", "0.5.0", SHA,
    )
    assert pin.url.endswith("acessilia_docstruct-0.5.0-py3-none-any.whl")


def test_a_pyproject_without_docstruct_has_no_pin() -> None:
    assert check.parse_pin(_pyproject("httpx>=0.27")) is None


def test_an_unrecognized_docstruct_pin_is_an_error_not_a_missing_one() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        check.parse_pin(_pyproject("acessilia-docstruct>=0.5"))


def test_only_docstruct_release_tags_count() -> None:
    tags = {"docstruct-v0.5.0", "docstruct-v0.10.0", "docstruct-v0.4.0", "v0.2.0", "docstruct-vnext"}
    assert check.tagged_versions(tags) == ["0.4.0", "0.5.0", "0.10.0"]


def test_a_pin_on_the_newest_release_for_the_core_version_agrees() -> None:
    assert check.evaluate("0.5.0", _pin("0.5.0"), RELEASES, SHA) == []


def test_a_bumped_but_unreleased_core_version_asks_nothing() -> None:
    assert check.evaluate("0.6.0", _pin("0.5.0"), RELEASES, SHA) == []


def test_a_release_the_toolbox_did_not_adopt_is_reported() -> None:
    [finding] = check.evaluate("0.5.0", _pin("0.4.0"), RELEASES, SHA)
    assert "behind" in finding and "docstruct-v0.5.0" in finding


def test_a_pin_newer_than_the_core_branch_is_reported() -> None:
    findings = check.evaluate("0.4.0", _pin("0.5.0"), RELEASES, SHA)
    assert any("newer than the core branch" in finding for finding in findings)


def test_a_pin_on_an_unpublished_release_is_reported() -> None:
    findings = check.evaluate("0.6.0", _pin("0.6.0"), RELEASES, None)
    assert any("not a published release" in finding for finding in findings)


def test_a_pin_whose_hash_is_not_the_published_wheel_is_reported() -> None:
    [finding] = check.evaluate("0.5.0", _pin("0.5.0"), RELEASES, "b" * 64)
    assert "sha256" in finding


def test_a_pin_on_another_repository_is_reported() -> None:
    # main() never fetches another repository's wheel, so it has no published hash.
    findings = check.evaluate("0.5.0", _pin("0.5.0", repository="someone/fork"), RELEASES, None)
    assert any("someone/fork" in finding for finding in findings)


def test_a_pin_whose_release_and_wheel_versions_differ_is_reported() -> None:
    line = _pin_line("0.5.0").replace("acessilia_docstruct-0.5.0-", "acessilia_docstruct-0.4.0-")
    pin = check.parse_pin(_pyproject(line))
    assert (pin.tag_version, pin.file_version) == ("0.5.0", "0.4.0")
    findings = check.evaluate("0.5.0", pin, RELEASES, SHA)
    assert any("differ" in finding for finding in findings)


def test_a_missing_pin_is_reported() -> None:
    assert check.evaluate("0.5.0", None, RELEASES, None) == [
        "the Toolbox does not pin acessilia-docstruct"
    ]


def test_versions_compare_as_numbers() -> None:
    # 0.10.0 is newer than 0.9.0, which a string comparison would invert.
    assert check.evaluate("0.10.0", _pin("0.10.0"), ["0.9.0", "0.10.0"], SHA) == []
    [finding] = check.evaluate("0.10.0", _pin("0.9.0"), ["0.9.0", "0.10.0"], SHA)
    assert "behind" in finding


def _offline(
    monkeypatch, pin_version: str, wheel: bytes, core_tags: set[str], unpublished: frozenset[str] = frozenset()
) -> None:
    """Fake network: the Toolbox pins ``pin_version``; tags in ``unpublished`` have no wheel."""
    sha = hashlib.sha256(wheel).hexdigest()

    def fetch(url: str) -> bytes:
        if url.endswith("pyproject.toml"):
            assert "/develop/" in url
            return _pyproject(_pin_line(pin_version, sha=sha)).encode()
        if any(f"docstruct-v{version}/" in url for version in unpublished):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return wheel

    monkeypatch.setattr(check, "_fetch", fetch)
    monkeypatch.setattr(check, "_remote_refs", lambda repository: (set(), core_tags))


def test_report_only_mode_warns_and_passes(monkeypatch, capsys) -> None:
    _offline(monkeypatch, "0.4.0", b"wheel", {"docstruct-v0.4.0", "docstruct-v0.5.0"})
    assert check.main(["develop", "--core-version", "0.5.0", "--report-only"]) == 0
    assert "::warning::the Toolbox is behind" in capsys.readouterr().out


def test_strict_mode_fails_on_a_finding(monkeypatch, capsys) -> None:
    _offline(monkeypatch, "0.4.0", b"wheel", {"docstruct-v0.4.0", "docstruct-v0.5.0"})
    assert check.main(["develop", "--core-version", "0.5.0"]) == 1
    assert "::error::the Toolbox is behind" in capsys.readouterr().out


def test_strict_mode_passes_when_the_pin_follows(monkeypatch, capsys) -> None:
    _offline(monkeypatch, "0.5.0", b"wheel", {"docstruct-v0.4.0", "docstruct-v0.5.0"})
    assert check.main(["develop", "--core-version", "0.5.0"]) == 0
    assert "follows the core" in capsys.readouterr().out


def test_a_network_failure_fails_strict_mode_and_warns_in_report_only(monkeypatch, capsys) -> None:
    def down(url: str) -> bytes:
        raise OSError("network unreachable")

    monkeypatch.setattr(check, "_fetch", down)
    assert check.main(["develop", "--core-version", "0.5.0"]) == 1
    assert "::error::cannot check" in capsys.readouterr().out
    assert check.main(["develop", "--core-version", "0.5.0", "--report-only"]) == 0
    assert "::warning::cannot check" in capsys.readouterr().out


def test_a_tag_whose_wheel_is_not_published_yet_does_not_make_the_toolbox_behind(monkeypatch, capsys) -> None:
    """Between the tag and the release workflow, the strict check must not fail (review of #498)."""
    _offline(
        monkeypatch, "0.5.0", b"wheel", {"docstruct-v0.5.0", "docstruct-v0.6.0"},
        unpublished=frozenset({"0.6.0"}),
    )
    assert check.main(["develop", "--core-version", "0.6.0"]) == 0
    out = capsys.readouterr().out
    assert "follows the core" in out
    assert "tags without a published wheel yet: 0.6.0" in out


def test_once_the_wheel_is_published_the_toolbox_is_behind(monkeypatch, capsys) -> None:
    _offline(monkeypatch, "0.5.0", b"wheel", {"docstruct-v0.5.0", "docstruct-v0.6.0"})
    assert check.main(["develop", "--core-version", "0.6.0"]) == 1
    assert "::error::the Toolbox is behind" in capsys.readouterr().out


def test_a_pin_on_a_tag_without_a_wheel_is_not_a_published_release(monkeypatch, capsys) -> None:
    _offline(
        monkeypatch, "0.6.0", b"wheel", {"docstruct-v0.5.0", "docstruct-v0.6.0"},
        unpublished=frozenset({"0.6.0"}),
    )
    assert check.main(["develop", "--core-version", "0.6.0"]) == 1
    assert "docstruct-v0.6.0 is not a published release" in capsys.readouterr().out


def test_a_failure_other_than_a_missing_wheel_cannot_decide(monkeypatch, capsys) -> None:
    _offline(monkeypatch, "0.5.0", b"wheel", {"docstruct-v0.5.0"})

    def server_error(version: str) -> str:
        raise urllib.error.HTTPError("url", 502, "Bad Gateway", None, None)

    monkeypatch.setattr(check, "_published_sha256", server_error)
    assert check.main(["develop", "--core-version", "0.5.0"]) == 1
    assert "::error::cannot check" in capsys.readouterr().out
