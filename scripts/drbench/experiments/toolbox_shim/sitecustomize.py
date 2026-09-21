"""Runtime shim (NOT repo code) — loaded via PYTHONPATH into the toolbox process only.

Bug worked around: acessilia-toolbox `core/normalization/builder.py:188` calls
`document.iterate_items(...)` and `:460` iterates `document.pages.items()`, but
`providers/mineru_document.py::MineruDocument` exposes neither (it returns a list
for `pages`). Docling works because `DoclingServeDocument` implements that facade.
This adds the missing facade to MineruDocument without touching the repo.
"""
from __future__ import annotations

try:
    from acessilia_toolbox.providers import mineru_document as _md
except Exception:  # toolbox not importable (other venv) — no-op
    _md = None

if _md is not None and not hasattr(_md.MineruDocument, "iterate_items"):
    # mineru block type -> docling label understood by builder.LABEL_TO_TYPE
    _LABEL = {
        "text": "text", "title": "section_header", "list": "list_item", "index": "text",
        "table": "table", "table_body": "table", "table_caption": "caption",
        "table_footnote": "footnote", "image": "picture", "image_body": "picture",
        "image_caption": "caption", "image_footnote": "footnote",
        "interline_equation": "formula", "code": "code", "code_body": "code",
        "code_caption": "caption", "header": "page_header", "footer": "page_footer",
        "page_number": "page_footer", "page_footnote": "footnote", "footnote": "footnote",
        "ref_text": "text", "aside_text": "text", "phonetic": "text",
    }

    class _Label:
        def __init__(self, v): self.value = v

    class _Origin:
        value = "TOPLEFT"

    class _BBox:
        coord_origin = _Origin()
        def __init__(self, b):
            b = list(b or [0, 0, 0, 0]) + [0, 0, 0, 0]
            self.l, self.t, self.r, self.b = (float(x) for x in b[:4])

    class _Prov:
        def __init__(self, page_no, bbox):
            self.page_no = page_no; self.bbox = _BBox(bbox); self.charspan = None

    class _Size:
        def __init__(self, w, h): self.width = w; self.height = h

    class _Page:
        def __init__(self, w, h): self.size = _Size(w, h)

    class _Item:
        def __init__(self, label, text, page_no, bbox, ref, level=None):
            self.label = _Label(label); self.text = text; self.prov = [_Prov(page_no, bbox)]
            self.self_ref = ref; self.parent = None; self.level = level

    def _span_text(span):
        t = span.get("type"); c = span.get("content") or span.get("latex") or ""
        if t == "inline_equation" and c:
            return f"${c}$"
        if t == "interline_equation" and c:
            return f"$${c}$$"
        if t == "table" and span.get("html"):
            return span["html"]
        return c or ""

    def _lines_text(block):
        out = ""
        for line in block.get("lines") or []:
            parts = [_span_text(s) for s in line.get("spans") or []]
            s = " ".join(p for p in parts if p).strip()
            if not s:
                continue
            if not out:
                out = s
            elif out.endswith("-") and s[:1].islower():  # de-hyphenate line break
                out = out[:-1] + s
            else:
                out += " " + s
        return out or None

    def _emit(block, page_no, counter):
        btype = str(block.get("type", "text"))
        if btype == "discarded":
            return
        subs = block.get("blocks") or []
        if subs:  # container (table/image/code): flatten sub-blocks in order
            for sb in subs:
                yield from _emit(sb, page_no, counter)
            return
        label = _LABEL.get(btype, "text")
        if btype in ("table", "table_body"):
            text = None
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    if span.get("html"):
                        text = span["html"]; break
                if text:
                    break
            text = text or _lines_text(block)
        elif btype == "interline_equation":
            latex = block.get("latex")
            if not latex:
                for line in block.get("lines") or []:
                    for span in line.get("spans") or []:
                        if span.get("content"):
                            latex = span["content"]; break
            text = f"$${latex}$$" if latex else None
        else:
            text = block.get("text") or _lines_text(block)
        if not text and label not in ("picture",):
            return
        counter[0] += 1
        level = 1 if label == "section_header" else None
        yield _Item(label, text, page_no, block.get("bbox"), f"#/mineru/{counter[0]}", level), 1

    def iterate_items(self, **_):
        counter = [0]
        for page in self._pages:
            page_no = int(page.get("page_idx", 0)) + 1
            for block in page.get("preproc_blocks") or []:
                yield from _emit(block, page_no, counter)

    def pages_dict(self):
        out = {}
        for idx, page in enumerate(self._pages):
            size = page.get("page_size") or [None, None]
            out[int(page.get("page_idx", idx)) + 1] = _Page(size[0], size[1])
        return out

    _md.MineruDocument.iterate_items = iterate_items
    _md.MineruDocument.pages = property(pages_dict)
    _md.MineruDocument.num_pages = lambda self: len(self._pages)
    print("[toolbox_shim] MineruDocument facade patched (iterate_items/pages/num_pages)")
