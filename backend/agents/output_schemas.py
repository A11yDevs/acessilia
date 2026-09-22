"""Validated output contracts shared by the Vision and Data agents."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

VISION_SCHEMA_INSTRUCTION = (
    "Retorne somente o objeto estruturado solicitado: use kind='description' e "
    "description para conteúdo visual/textual, ou kind='formula' e formula_latex "
    "quando a região for predominantemente uma fórmula. Sempre informe language, "
    "confidence, mentioned_elements e warnings."
)

DATA_SCHEMA_INSTRUCTION = (
    "Retorne somente o objeto estruturado solicitado: use kind='table' com rows/cells "
    "para tabelas, ou kind='formula' com latex para fórmulas. Sempre informe language, "
    "confidence e warnings."
)


class AgentOutput(BaseModel):
    """Base contract that rejects fields outside the declared agent schema."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VisionOutput(AgentOutput):
    """Structured visual description, optionally representing a formula."""

    kind: Literal["description", "formula"] = Field(
        description="Whether the region is a visual description or a mathematical formula."
    )
    description: str = Field(
        default="",
        description="Objective accessible description or transcription of the visible content.",
    )
    language: str = Field(
        min_length=2,
        max_length=35,
        description="BCP 47 language tag for the description, or 'und' when unknown.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the extracted visual information, from 0 to 1.",
    )
    mentioned_elements: list[str] = Field(
        default_factory=list,
        description="Concrete visual elements explicitly mentioned in the description.",
    )
    formula_latex: str | None = Field(
        default=None,
        description="LaTeX when the region contains predominantly a mathematical formula.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Uncertainties such as illegible or partially occluded content.",
    )

    @model_validator(mode="after")
    def validate_content(self) -> "VisionOutput":
        if self.kind == "description" and not self.description:
            raise ValueError("description is required when kind is 'description'")
        if self.kind == "formula" and not self.formula_latex:
            raise ValueError("formula_latex is required when kind is 'formula'")
        if self.kind == "description" and self.formula_latex is not None:
            raise ValueError("formula_latex is only allowed when kind is 'formula'")
        return self


class DataCell(AgentOutput):
    """One table cell with the structural attributes used by the canonical AST."""

    text: str = Field(description="Cell contents; use an empty string for a visible empty cell.")
    header: bool = Field(default=False, description="Whether this is a header cell.")
    scope: Literal["none", "row", "col", "rowgroup", "colgroup"] = Field(
        default="none",
        description="Accessible header scope for the cell.",
    )
    rowspan: int = Field(default=1, ge=1, description="Number of rows occupied by the cell.")
    colspan: int = Field(default=1, ge=1, description="Number of columns occupied by the cell.")


class DataRow(AgentOutput):
    """One ordered row in a table."""

    cells: list[DataCell] = Field(min_length=1)


class DataOutput(AgentOutput):
    """Structured extraction of either a table or a mathematical formula."""

    kind: Literal["table", "formula"]
    rows: list[DataRow] = Field(
        default_factory=list,
        description="Ordered table rows; required for table output and empty for formulas.",
    )
    latex: str | None = Field(
        default=None,
        description="Extracted LaTeX; required for formula output and absent for tables.",
    )
    caption: str | None = Field(default=None, description="Visible table caption, if present.")
    language: str = Field(
        min_length=2,
        max_length=35,
        description="BCP 47 language tag for textual content, or 'und' when unknown.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(
        default_factory=list,
        description="Uncertainties such as illegible cells or ambiguous mathematical symbols.",
    )

    @model_validator(mode="after")
    def validate_content(self) -> "DataOutput":
        if self.kind == "table":
            if not self.rows:
                raise ValueError("rows are required when kind is 'table'")
            if self.latex is not None:
                raise ValueError("latex is only allowed when kind is 'formula'")
        else:
            if not self.latex:
                raise ValueError("latex is required when kind is 'formula'")
            if self.rows:
                raise ValueError("rows are only allowed when kind is 'table'")
            if self.caption is not None:
                raise ValueError("caption is only allowed when kind is 'table'")
        return self

    def table_rows(self) -> list[list[str]]:
        """Return the simple row representation retained for compatibility."""
        return [[cell.text for cell in row.cells] for row in self.rows]

    def table_ast(self) -> dict[str, Any]:
        """Build the canonical table AST without reparsing model-generated text."""
        if self.kind != "table":
            raise ValueError("table_ast is only available for table output")

        ast_rows: list[dict[str, Any]] = []
        for row in self.rows:
            cells: list[dict[str, Any]] = []
            for cell in row.cells:
                canonical_cell: dict[str, Any] = {"text": cell.text}
                if cell.header or cell.scope != "none":
                    canonical_cell["header"] = True
                if cell.scope != "none":
                    canonical_cell["scope"] = cell.scope
                if cell.rowspan > 1:
                    canonical_cell["rowspan"] = cell.rowspan
                if cell.colspan > 1:
                    canonical_cell["colspan"] = cell.colspan
                cells.append(canonical_cell)
            ast_rows.append({"cells": cells})

        # Promote only leading, fully marked header rows. Mixed rows stay in
        # the body so row headers (for example the first cell of every row)
        # retain their cell-level semantics instead of turning the whole row
        # into a column-header row. Keep at least one body row because the
        # canonical table contract requires a non-empty body.
        header_count = 0
        for row in self.rows[:-1]:
            if not all(
                (cell.header or cell.scope in {"col", "colgroup"})
                and cell.scope not in {"row", "rowgroup"}
                for cell in row.cells
            ):
                break
            header_count += 1

        table_ast: dict[str, Any] = {"body": ast_rows[header_count:]}
        if header_count:
            table_ast["header"] = ast_rows[:header_count]
        if self.caption:
            table_ast["caption"] = self.caption
        if self.warnings:
            table_ast["metadata"] = {"warnings": list(self.warnings)}
        return table_ast


StructuredOutput = VisionOutput | DataOutput
OutputModel = TypeVar("OutputModel", bound=AgentOutput)


def validate_structured_content(content: Any, schema: type[OutputModel]) -> OutputModel:
    """Validate Agno content even when a provider returns JSON instead of a model."""
    if isinstance(content, schema):
        return content
    if isinstance(content, str):
        return schema.model_validate_json(content)
    return schema.model_validate(content)
