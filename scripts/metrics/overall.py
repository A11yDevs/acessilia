"""Overall page aggregate per the Dr.DocBench EvalAI contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageScores:
    """Component scores for one page. ``None`` = non-scorable component."""

    item_id: str
    text_ed: float | None = None          # 0–1, lower better
    teds: float | None = None             # 0–100
    cdm: float | None = None              # 0–100
    reading_order: float | None = None    # 0–100

    def components_0_100(self) -> dict[str, float]:
        """Return scorably-available components on a unified 0–100 scale."""
        comps: dict[str, float] = {}
        if self.text_ed is not None:
            comps["text_ed"] = (1.0 - self.text_ed) * 100.0
        if self.teds is not None:
            comps["teds"] = self.teds
        if self.cdm is not None:
            comps["cdm"] = self.cdm
        if self.reading_order is not None:
            comps["reading_order"] = self.reading_order
        return comps

    def overall(self) -> float | None:
        """Mean of available components; None when the page is non-scorable."""
        comps = self.components_0_100()
        if not comps:
            return None
        return sum(comps.values()) / len(comps)


def overall_score(pages: list[PageScores]) -> dict[str, float]:
    """Aggregate Overall across scorable pages, plus per-component means.

    Non-scorable pages (no available components) are excluded.
    """
    component_sums: dict[str, list[float]] = {}
    overall_values: list[float] = []

    for page in pages:
        comps = page.components_0_100()
        if not comps:
            continue
        overall_values.append(sum(comps.values()) / len(comps))
        for name, value in comps.items():
            component_sums.setdefault(name, []).append(value)

    report = {
        name: sum(values) / len(values)
        for name, values in component_sums.items()
    }
    report["overall"] = (
        sum(overall_values) / len(overall_values) if overall_values else 0.0
    )
    return report


__all__ = ["PageScores", "overall_score"]
