"""Ordered, format-independent traversal of canonical section/block mappings.

Consumers own block selection, rendering, labels and result aggregation. The
walker supplies legacy-title metadata without imposing an omission policy.
Callbacks receive the original mappings and must treat them as read-only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from docstruct.sections import explicit_section_title, section_title_alias

__all__ = [
    "BLOCK_TYPES", "BlockCallback", "BlockContext", "BlockSelector",
    "SectionCallback", "SectionContext", "Visitor", "walk",
]

BLOCK_TYPES = (
    "heading", "paragraph", "list", "table", "image", "code", "math",
    "quote", "details", "note", "warning",
)
T = TypeVar("T")


@dataclass(frozen=True)
class SectionContext:
    """Original section and its zero-based sibling-index path; root depth is 0."""

    data: dict[str, Any]
    path: tuple[int, ...]

    @property
    def depth(self) -> int:
        return len(self.path) - 1

    @property
    def legacy_title(self) -> dict[str, Any] | None:
        return explicit_section_title(self.data)

    @property
    def title_alias(self) -> str:
        return section_title_alias(self.data)


@dataclass(frozen=True)
class BlockContext:
    """Containing section and original block index, before any selection."""

    section: SectionContext
    index: int

    @property
    def is_legacy_title(self) -> bool:
        return self.index == 0 and self.section.legacy_title is not None


BlockCallback = Callable[[dict[str, Any], BlockContext], T | None]
SectionCallback = Callable[[SectionContext], T | None]
BlockSelector = Callable[[dict[str, Any], BlockContext], bool]


@dataclass(frozen=True, kw_only=True)
class Visitor(Generic[T]):
    """Per-type callbacks, a mandatory fallback, and optional section hooks.

    An unset known-type callback also uses default. Returning None emits no
    result; every other value, including falsey values, is yielded unchanged.
    """

    default: BlockCallback[T]
    heading: BlockCallback[T] | None = None
    paragraph: BlockCallback[T] | None = None
    list: BlockCallback[T] | None = None
    table: BlockCallback[T] | None = None
    image: BlockCallback[T] | None = None
    code: BlockCallback[T] | None = None
    math: BlockCallback[T] | None = None
    quote: BlockCallback[T] | None = None
    details: BlockCallback[T] | None = None
    note: BlockCallback[T] | None = None
    warning: BlockCallback[T] | None = None
    enter_section: SectionCallback[T] | None = None
    leave_section: SectionCallback[T] | None = None

    def __post_init__(self) -> None:
        if not callable(self.default):
            raise TypeError("default must be a callable block handler")


def walk(
    document: dict[str, Any],
    visitor: Visitor[T],
    select: BlockSelector | None = None,
) -> Iterator[T]:
    """Lazily yield section entry, selected blocks, children, then section exit.

    Default selection includes all blocks, including legacy title headings.
    Selection never prunes child sections or suppresses section hooks. Callback
    and selector exceptions propagate; no format/profile policy is applied.
    """
    yield from _sections(document.get("sections", []), (), visitor, select)


def _sections(
    sections: Iterable[dict[str, Any]],
    parent_path: tuple[int, ...],
    visitor: Visitor[T],
    select: BlockSelector | None,
) -> Iterator[T]:
    for position, section in enumerate(sections):
        context = SectionContext(section, (*parent_path, position))
        yield from _emit(visitor.enter_section, context)
        for index, block in enumerate(section.get("blocks", [])):
            block_context = BlockContext(context, index)
            if select is not None and not select(block, block_context):
                continue
            kind = block.get("type")
            callback = getattr(visitor, kind) if isinstance(kind, str) and kind in BLOCK_TYPES else None
            yield from _emit(visitor.default if callback is None else callback, block, block_context)
        yield from _sections(section.get("children", []), context.path, visitor, select)
        yield from _emit(visitor.leave_section, context)


def _emit(callback: Callable[..., T | None] | None, *args: Any) -> Iterator[T]:
    if callback is not None:
        result = callback(*args)
        if result is not None:
            yield result
