"""Extrator que consome docling-serve via HTTP (Docker).

Útil em ambientes onde o pacote docling não pode ser instalado nativamente
(macOS com restrições de compatibilidade), mas o docling-serve está
disponível em container.

Retorna um DoclingExtraction com um proxy que implementa iterate_items()
para compatibilidade com o builder existente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

import httpx

from backend.core.manifest.docling_extractor import DoclingExtraction


@dataclass(frozen=True)
class DoclingServeConfig:
    """Configuração para conexão com docling-serve."""
    base_url: str = "http://localhost:5001"
    timeout_seconds: int = 300


class DoclingDocumentProxy:
    """Proxy puro-Python para um docling.Document a partir de JSON.

    Implementa iterate_items() percorrendo a árvore JSON do documento
    (body → groups → texts/pictures/tables) sem depender do pacote docling.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._pages: dict[int, Any] = {}
        self._build_pages()

    def _build_pages(self) -> None:
        raw_pages = self._data.get("pages", {})
        for page_no_str, page_info in raw_pages.items():
            page_no = int(page_no_str)
            size = page_info.get("size", {})
            self._pages[page_no] = page_info

    @property
    def pages(self) -> dict[int, Any]:
        return self._pages

    def iterate_items(
        self,
        with_groups: bool = True,
        traverse_pictures: bool = True,
    ) -> Iterator[tuple[Any, int]]:
        """Itera sobre todos os itens do documento, compatível com docling.Document.

        Yields (item_proxy, tree_level) tuples.
        """
        body = self._data.get("body")
        if body:
            yield from self._walk_item(body, 0, with_groups=with_groups)

        groups = self._data.get("groups", [])
        for group in groups:
            yield from self._walk_item(group, 0, with_groups=with_groups)

    def _walk_item(
        self,
        item: dict[str, Any],
        level: int,
        *,
        with_groups: bool,
    ) -> Iterator[tuple[Any, int]]:
        proxy = _DoclingItemProxy(item, self._data)
        yield proxy, level

        children = item.get("children", [])
        for child_ref in children:
            resolved = self._resolve_ref(child_ref)
            if resolved is None:
                continue
            child_label = resolved.get("label", "")
            if child_label == "group" and not with_groups:
                yield from self._walk_item(resolved, level + 1, with_groups=with_groups)
            else:
                yield from self._walk_item(resolved, level + 1, with_groups=with_groups)

    def _resolve_ref(self, ref: dict[str, str] | str) -> dict[str, Any] | None:
        """Resolve uma referência $ref para o item real no JSON."""
        ref_path = ref if isinstance(ref, str) else ref.get("$ref", "")
        if not ref_path:
            return None
        # ref_path looks like "#/texts/0" or "#/body"
        parts = ref_path.lstrip("#/").split("/")
        current: Any = self._data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return None
            else:
                return None
        return current if isinstance(current, dict) else None


class _DoclingItemProxy:
    """Proxy para um item individual do documento docling.

    Expõe os atributos que _build_elements() espera: label, text,
    self_ref, parent, prov, etc.
    """

    def __init__(self, data: dict[str, Any], root: dict[str, Any]) -> None:
        self._data = data
        self._root = root

    def __getattr__(self, name: str) -> Any:
        if name == "label":
            return self._data.get("label", "")
        if name == "text":
            return self._data.get("text", "")
        if name == "self_ref":
            return self._data.get("self_ref")
        if name == "parent":
            parent_ref = self._data.get("parent")
            if parent_ref and isinstance(parent_ref, dict) and "$ref" in parent_ref:
                resolved = self._resolve_ref(parent_ref["$ref"])
                return resolved
            return parent_ref
        if name == "prov":
            return self._data.get("prov", [])
        if name == "children":
            return self._data.get("children", [])
        if name == "meta":
            return self._data.get("meta")
        if name == "type":
            return self._data.get("type", "")
        if name == "name":
            return self._data.get("name", "")
        if name == "image":
            return self._data.get("image")
        if name == "caption":
            captions = self._data.get("captions", [])
            return captions[0] if captions else None
        if name == "enum_label_id":
            return self._data.get("enum_label_id")
        raise AttributeError(f"_DoclingItemProxy has no attribute '{name}'")

    def _resolve_ref(self, ref_path: str) -> Any:
        parts = ref_path.lstrip("#/").split("/")
        current: Any = self._root
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return None
            else:
                return None
        return current


class DoclingServeManifestExtractor:
    """Extrator que consome docling-serve via HTTP (Docker).

    Interface compatível com DoclingManifestExtractor.extract(source_path).
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:5001",
        enable_ocr: bool = True,
        timeout_seconds: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.enable_ocr = enable_ocr
        self.timeout_seconds = timeout_seconds

    def extract(self, source_path: Path) -> DoclingExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()

        with open(source_path, "rb") as f:
            files = {"files": (source_path.name, f, "application/pdf")}
            data: dict[str, Any] = {"to_formats": "json"}
            if not self.enable_ocr:
                data["do_ocr"] = "false"

            response = httpx.post(
                f"{self.base_url}/v1/convert/file",
                files=files,
                data=data,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            result = response.json()

        duration_ms = round((perf_counter() - started_clock) * 1000)
        completed_at = datetime.now(timezone.utc)

        json_content = result.get("document", {}).get("json_content", {})
        proxy = DoclingDocumentProxy(json_content)

        return DoclingExtraction(
            document=proxy,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            version=result.get("document", {}).get("json_content", {}).get("version", "unknown"),
            configuration={
                "ocr": self.enable_ocr,
                "table_structure": True,
                "remote_services": False,
                "docling_serve_url": self.base_url,
            },
        )