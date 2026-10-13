from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from backend.core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    ProcessingManifest,
    SourceDocument,
)
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.planner_agent import PlannerAgent
from scripts.pmv import main


def make_manifest() -> ProcessingManifest:
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)
    return ProcessingManifest(
        manifest_id="manifest-test-r1",
        created_at=now,
        source=SourceDocument(
            document_id="doc-test",
            filename="test.pdf",
            path="/tmp/test.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={"ocr": False},
        ),
        title="Documento de teste",
        language="pt-BR",
        pages=[],
        elements=[
            ManifestElement(
                id="element-1",
                type="picture",
                raw_label="picture",
                reading_order=1,
                hierarchy_level=0,
            )
        ],
        obligations=[
            Obligation(
                id="o-extract",
                kind="extract-image",
                target_ids=["element-1"],
                admissible_methods=["docling"],
                method_costs={"docling": 5},
                rationale="Extrair a imagem",
            ),
            Obligation(
                id="o-describe",
                kind="describe-image",
                target_ids=["element-1"],
                dependencies=["o-extract"],
                admissible_methods=["vision", "human-review"],
                method_costs={"vision": 10, "human-review": 100},
                rationale="Descrever a imagem",
            ),
        ],
        summary=ManifestSummary(
            page_count=0,
            element_count=1,
            observation_count=0,
            obligation_count=2,
            element_types={"picture": 1},
        ),
    )


def test_domain_bundle_validates_matching_version():
    domain = DomainBundle.load()

    assert domain.name == "acessilia-obligations"
    assert domain.version == "2.3"
    assert len(domain.domain_sha256) == 64


def test_compiler_closes_dependencies_and_requires_metric():
    compiled, plan = PlannerAgent().plan(
        make_manifest(),
        selected_roots=["o-describe"],
    )

    assert compiled.projection.selected == ("o-describe", "o-extract")
    assert "(:metric minimize (total-cost))" in compiled.text
    assert "(depends-on o-describe o-extract)" in compiled.text
    assert [step.action for step in plan.steps] == [
        "start-job",
        "execute-obligation",
        "execute-obligation",
        "complete-job",
    ]
    assert plan.steps[1].obligation_id == "o-extract"
    assert plan.steps[2].method == "vision"
    assert plan.expected_total_cost == 15


def test_compiler_rejects_selected_obligation_without_method():
    manifest = make_manifest()

    with pytest.raises(ValueError, match="Nenhum método"):
        PlannerAgent().plan(
            manifest,
            selected_roots=["o-describe"],
            unavailable_methods=["docling", "vision", "human-review"],
        )


def _fake_fast_downward(
    directory: Path,
    plan_lines: list[str],
) -> Path:
    executable = directory / "fake-fast-downward.py"
    plan_text = "\n".join(plan_lines) + "\n; cost = 15 (unit cost)\n"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path('sas_plan').write_text({plan_text!r}, encoding='utf-8')\n"
        "print('Expanded 7 state(s).')\n"
        "print('Evaluated 8 state(s).')\n"
        "print('Generated 12 state(s).')\n"
        "print('Plan cost: 15')\n"
        "print('Plan length: 4 step(s).')\n"
        "print('Search time: 0.002s')\n"
        "print('Total time: 0.005s')\n",
        encoding="utf-8",
    )
    return executable


def _expected_fast_downward_plan() -> list[str]:
    return [
        "(start-job)",
        "(execute-obligation o-extract extract-image docling)",
        "(execute-obligation o-describe describe-image vision)",
        "(complete-job)",
    ]


def test_both_planners_produce_identical_validated_plans(tmp_path):
    executable = _fake_fast_downward(
        tmp_path, _expected_fast_downward_plan()
    )

    compiled, plans, report = PlannerAgent().compare(
        make_manifest(),
        selected_roots=["o-describe"],
        fast_downward=executable,
    )

    assert set(plans) == {"internal", "fast-downward"}
    assert report.problem_sha256 == compiled.sha256
    assert report.comparison.verdict == "identical"
    assert report.comparison.same_expected_total_cost is True
    assert report.comparison.same_method_selection is True
    assert (
        report.outcomes["fast-downward"].statistics["expanded_states"]
        == 7
    )


def test_comparison_recognizes_equivalent_independent_order(tmp_path):
    manifest = make_manifest()
    manifest.obligations[1].dependencies = []
    executable = _fake_fast_downward(
        tmp_path, _expected_fast_downward_plan()
    )

    _, _, report = PlannerAgent().compare(
        manifest,
        fast_downward=executable,
    )

    assert report.comparison.verdict == "equivalent"
    assert report.comparison.same_action_sequence is False
    assert report.comparison.same_action_multiset is True
    assert report.comparison.notes


def test_comparison_records_backend_failure_without_losing_internal_plan():
    _, plans, report = PlannerAgent().compare(
        make_manifest(),
        selected_roots=["o-describe"],
        fast_downward=None,
    )

    assert set(plans) == {"internal"}
    assert report.comparison.verdict == "inconclusive"
    assert report.outcomes["internal"].status == "solved"
    assert report.outcomes["fast-downward"].status == "failed"
    assert report.outcomes["fast-downward"].error_type == "ValueError"


def test_cli_both_writes_backend_plans_and_comparison(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            make_manifest().model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )
    executable = _fake_fast_downward(
        tmp_path, _expected_fast_downward_plan()
    )
    output = tmp_path / "output"

    exit_code = main(
        [
            "plan",
            str(manifest_path),
            "-o",
            str(output),
            "--select",
            "o-describe",
            "--planner",
            "both",
            "--fast-downward",
            str(executable),
        ]
    )

    assert exit_code == 0
    assert (output / "problem.pddl").is_file()
    assert (output / "nominal-plan.internal.json").is_file()
    assert (output / "nominal-plan.fast-downward.json").is_file()
    assert (output / "nominal-plan.json").is_file()
    payload = json.loads(
        (output / "planning-comparison.json").read_text(encoding="utf-8")
    )
    assert payload["comparison"]["verdict"] == "identical"


def test_domain_v23_documents_the_new_obligations():
    from backend.core.planning.domain_bundle import V23_OBLIGATION_KINDS

    domain = DomainBundle.load()
    description = domain.description_path.read_text(encoding="utf-8")

    assert domain.version == "2.3"
    for kind in V23_OBLIGATION_KINDS:
        assert kind in description, f"obrigação {kind} não documentada"


def test_domain_v23_keeps_the_v22_structure():
    domain = DomainBundle.load()
    text = domain.domain_path.read_text(encoding="utf-8")

    # A v2.3 não muda a estrutura do domínio: só a descrição ganha as obrigações.
    assert "(:action execute-obligation" in text
    assert "(:derived (ready ?o - obligation)" in text
    assert "(increase (total-cost) (execution-cost ?m ?o))" in text


def test_domain_v23_rejects_a_description_missing_a_new_obligation(tmp_path):
    domain = DomainBundle.load()
    broken = tmp_path / "domain_description_v2.3.md"
    broken.write_text(
        domain.description_path.read_text(encoding="utf-8").replace("chunk-verse", "x"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="chunk-verse"):
        DomainBundle.load(domain_path=domain.domain_path, description_path=broken)


class TestV23Costs:
    def test_toda_obrigacao_v23_tem_metodos_com_custo(self):
        from backend.core.manifest.builder import (
            DEFAULT_METHOD_COSTS,
            V23_OBLIGATION_BY_KIND,
        )
        from backend.core.planning.domain_bundle import V23_OBLIGATION_KINDS

        assert set(V23_OBLIGATION_KINDS) == set(V23_OBLIGATION_BY_KIND)
        for kind, (_, methods) in V23_OBLIGATION_BY_KIND.items():
            assert methods, f"{kind} sem métodos"
            for method in methods:
                assert method in DEFAULT_METHOD_COSTS, f"{kind}: {method} sem custo"

    def test_metodos_deterministicos_custam_menos_que_os_de_modelo(self):
        from backend.core.manifest.builder import DEFAULT_METHOD_COSTS as C

        deterministic = (
            "agreement-rule", "xycut-order", "skeleton-order", "latex-normalizer",
            "rep-guard", "tailjoin", "tailjoin-positioned", "verse-chunker",
            "line-number-extractor", "norm-fix",
        )
        model_based = ("vlm-pairwise-judge", "table-specialist", "dual-provider-fusion")
        assert max(C[m] for m in deterministic) < min(C[m] for m in model_based)

    def test_human_review_e_o_mais_caro(self):
        from backend.core.manifest.builder import DEFAULT_METHOD_COSTS as C

        assert C["human-review"] == max(C.values())

    def test_join_tail_prefere_a_variante_posicionada(self):
        from backend.core.manifest.builder import V23_OBLIGATION_BY_KIND

        methods = V23_OBLIGATION_BY_KIND["join-tail-blocks"][1]
        assert methods.index("tailjoin-positioned") < methods.index("tailjoin")

    def test_fuse_providers_prefere_a_fusao_dual(self):
        from backend.core.manifest.builder import V23_OBLIGATION_BY_KIND

        methods = V23_OBLIGATION_BY_KIND["fuse-providers"][1]
        assert methods[0] == "dual-provider-fusion"

    def test_custos_sao_inteiros_nao_negativos(self):
        from backend.core.manifest.builder import DEFAULT_METHOD_COSTS as C

        assert all(isinstance(v, int) and v >= 0 for v in C.values())
