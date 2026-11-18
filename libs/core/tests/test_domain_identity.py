"""The PDDL domain's identity changes only on purpose (review of #572).

``DomainBundle`` hashes the domain and its description byte for byte; the
processing cache key carries both, and the executor refuses a saved plan
whose description hash differs (``EXE_DOMAIN_DESCRIPTION_CHANGED``). Any edit
to these files, even a renamed module path inside the description, would
fail every job resumed from a plan checkpoint after a deploy. When a change
is intended, update the hash here with the domain's version and the plan
migration it needs.
"""

from __future__ import annotations

import hashlib

import pytest

from acessilia_core.planning.domain_bundle import DEFAULT_DOMAIN_DIR, DomainBundle

#: SHA-256 of each shipped domain file, as released.
PINNED = {
    "domain_v2.2.pddl": "c9c597122cef7171",
    "domain_description_v2.2.md": "453e4b0ea783d61c",
    "domain_v2.3.pddl": "07d0910eafa32624",
    "domain_description_v2.3.md": "c4135d29749ebf92",
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_a_shipped_domain_file_keeps_its_hash(name) -> None:
    digest = hashlib.sha256((DEFAULT_DOMAIN_DIR / name).read_bytes()).hexdigest()

    assert digest.startswith(PINNED[name]), (
        f"{name} changed: saved plans would no longer resume; bump the domain "
        "version and migrate the plans instead of editing it in place"
    )


def test_every_shipped_domain_file_is_pinned() -> None:
    shipped = {path.name for path in DEFAULT_DOMAIN_DIR.iterdir() if path.is_file()}

    assert shipped == set(PINNED)


def test_the_default_bundle_is_the_pinned_one() -> None:
    bundle = DomainBundle.load()

    assert bundle.domain_sha256.startswith(PINNED["domain_v2.3.pddl"])
    assert bundle.description_sha256.startswith(PINNED["domain_description_v2.3.md"])
