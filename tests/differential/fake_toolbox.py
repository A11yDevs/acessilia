"""A deterministic Toolbox, served in process, for the differential runs (#849).

Every call the core makes leaves it over HTTP: the capability clients of the
SDK (``/v1/capabilities/{id}:execute``, ``/v1/artifacts``) and, with
``AI_CLIENT=toolbox``, the agents' chats through the VLM gateway
(``/v1/vlm``). That boundary is the same in every core version, so the same
fake answers a run of the current tree and of an older one, without patching
anything inside the core: :func:`installed` routes every ``httpx`` client to
it.

The answers come from the case (``cases/<name>/case.json``):

- ``document``: what ``document.structure.extract`` returns, a
  ProcessingManifest-compatible document;
- ``text_spans``: the text layer per page, for ``document.text.spans``;
- ``vision``: per element id (or ``page-<number>`` for a whole page), the
  fields a vision answer gets: a picture's description, a region's kind and
  LaTeX, a table's rows;
- ``latex``: per formula id, what ``math.recognize`` reads;
- ``tables``: per table id, the HTML ``table.recognize`` returns.

A rendered image does not carry the region it shows, and a newer core may
downscale or re-encode it. So each ``pdf.render`` gets a solid colour that
indexes the clip it rendered, and the VLM and ``math.recognize`` answers
decode the colour back to the region, then to the element whose box holds its
centre. Anything the fake does not know is answered 404 and recorded in
``unhandled``, which the runner reports.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import re
from collections.abc import Iterator
from email.parser import BytesParser
from email.policy import HTTP
from typing import Any

import httpx

#: The host the runner points ``TOOLBOX_BASE_URL`` at. A ``.test`` host, so
#: the root conftest's guard against a real Toolbox lets it through.
BASE_URL = "http://toolbox.differential.test"

_EXECUTE = re.compile(r"^/v1/capabilities/(?P<capability>[^/:]+):execute$")
_ARTIFACT = re.compile(r"^/v1/artifacts/(?P<artifact_id>[^/]+)$")

#: Colour step between two levels of a channel: large enough to survive a
#: lossy re-encoding of a solid image.
_STEP = 32


class FakeToolbox:
    """The Toolbox of one case. ``calls`` lists the capabilities it served."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.artifacts: dict[str, bytes] = {}
        self.renders: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.unhandled: list[str] = []

    # Transport.

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            if path.startswith("/v1/vlm"):
                self.calls.append("vlm")
                return self._vlm(request)
            match = _EXECUTE.match(path)
            if match and request.method == "POST":
                capability = match["capability"]
                self.calls.append(capability)
                form, files = _form(request)
                answer = getattr(self, "_" + capability.replace(".", "_"), None)
                if answer is not None:
                    document = answer(form, files)
                    if document is not None:
                        return _succeeded(capability, form.get("provider", "fake"), document)
            if path == "/v1/artifacts" and request.method == "POST":
                _, files = _form(request)
                return httpx.Response(200, json=self._store(next(iter(files.values()))))
            match = _ARTIFACT.match(path)
            if match and request.method == "GET":
                content = self.artifacts.get(match["artifact_id"].removeprefix("sha256:"))
                if content is not None:
                    return httpx.Response(200, content=content)
            if path == "/v1/health":
                return httpx.Response(200, json={"status": "ok"})
        except _Unanswerable as reason:
            self.unhandled.append(f"{request.method} {path}: {reason}")
            return _error(422, "unanswerable", str(reason))
        self.unhandled.append(f"{request.method} {path}")
        return _error(404, "not_found", f"the differential Toolbox does not serve {path}")

    # Artifacts.

    def _store(self, content: bytes, media_type: str = "application/octet-stream") -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        self.artifacts[digest] = content
        return {
            "artifact_id": f"sha256:{digest}",
            "digest": f"sha256:{digest}",
            "media_type": media_type,
            "size": len(content),
            "store": "differential",
        }

    def _input(self, form: dict[str, str], files: dict[str, bytes]) -> bytes:
        if files:
            return next(iter(files.values()))
        artifact = (form.get("artifact_id") or "").removeprefix("sha256:")
        if artifact in self.artifacts:
            return self.artifacts[artifact]
        raise _Unanswerable(f"unknown input artifact {form.get('artifact_id')!r}")

    # Capabilities: each returns the envelope's ``document``.

    def _media_inspect(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        content = self._input(form, files)
        pages = self.case["document"].get("pages") or [{}]
        return {
            "media_type": "application/pdf",
            "declared_media_type": "application/pdf",
            "file_size_bytes": len(content),
            "is_image": False,
            "is_pdf": True,
            "page_count": len(pages),
            "page_count_source": "differential",
            "artifact_nature": "document",
        }

    def _document_structure_extract(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        self._input(form, files)
        # The envelope's ``document`` is the extraction result; the core reads
        # the manifest-compatible payload from its own ``document`` key.
        return self.case["document"]

    def _pdf_render(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        self._input(form, files)
        parameters = json.loads(form.get("parameters") or "{}")
        page = int(parameters.get("page_number") or parameters.get("page") or 1)
        size = self._page_size(page)
        box = _box(parameters.get("clip") or parameters.get("bbox"), size[1]) or (0.0, 0.0, *size)
        clip = dict(zip(("left", "top", "right", "bottom"), box))
        index = len(self.renders)
        self.renders.append({"page": page, "clip": clip})
        png = _solid_png(index)
        reference = self._store(png, "image/png")
        return {
            "artifact_id": reference["artifact_id"],
            "media_type": "image/png",
            "size_bytes": len(png),
            "page_number": page,
            "page_count": len(self.case["document"].get("pages") or [1]),
            "page_width": size[0],
            "page_height": size[1],
            "clip": clip,
            "dpi": parameters.get("dpi", 144),
            "width": 64,
            "height": 64,
        }

    def _document_text_spans(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        self._input(form, files)
        parameters = json.loads(form.get("parameters") or "{}")
        wanted = parameters.get("pages")
        spans = self.case.get("text_spans") or {}
        pages = []
        for number, (width, height) in enumerate(self._page_sizes(), start=1):
            if wanted and number not in wanted:
                continue
            pages.append({
                "page_number": number, "width": width, "height": height, "rotation": 0,
                "lines": spans.get(str(number), []),
            })
        return {"page_count": len(self._page_sizes()), "coord_origin": "TOPLEFT", "pages": pages}

    def _math_convert(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        latex = _latex(form, files)
        return {
            "latex": latex,
            "mathml": f'<math xmlns="http://www.w3.org/1998/Math/MathML"><mtext>{_escape(latex)}</mtext></math>',
            "direction": "latex-to-mathml",
        }

    def _math_verbalize(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        latex = _latex(form, files)
        return {"latex": latex, "verbalized": f"spoken {latex}", "language": "pt-BR"}

    def _math_recognize(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        element = self._element_of_image(self._input(form, files))
        latex = (self.case.get("latex") or {}).get(element or "", "")
        return {"formulas": [{"latex": latex, "confidence": 0.99}] if latex else []}

    def _table_recognize(self, form: dict[str, str], files: dict[str, bytes]) -> dict[str, Any]:
        element = self._element_of_image(self._input(form, files))
        html = (self.case.get("tables") or {}).get(element or "", "<table></table>")
        return {
            "greedy": {"text": html, "finish": "stop"},
            "samples": [{"text": html, "finish": "stop", "seed": 0}],
            "model": "differential",
        }

    # The VLM gateway (OpenAI chat completions).

    def _vlm(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        element = None
        for message in body.get("messages", []):
            for part in message.get("content") or [] if isinstance(message.get("content"), list) else []:
                url = (part.get("image_url") or {}).get("url", "") if isinstance(part, dict) else ""
                if url.startswith("data:"):
                    element = self._element_of_image(base64.b64decode(url.split(",", 1)[1]))
        schema = _response_schema(body)
        answer = _instance(schema, (self.case.get("vision") or {}).get(element or "", {}))
        content = json.dumps(answer, ensure_ascii=False) if schema else str(answer or "")
        return httpx.Response(200, json={
            "id": "chatcmpl-differential",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "differential"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    # Regions.

    def _element_of_image(self, content: bytes) -> str | None:
        """The element whose box holds the centre of the region ``content``
        shows, else ``page-<number>``; ``None`` for an image no render made."""
        index = _decode_index(content)
        if index is None or index >= len(self.renders):
            return None
        render = self.renders[index]
        clip = _box(render["clip"])
        if clip is None:
            return None
        centre = ((clip[0] + clip[2]) / 2, (clip[1] + clip[3]) / 2)
        for element in self.case["document"].get("elements", []):
            for provenance in element.get("provenance") or []:
                box = _box(provenance.get("bbox"), self._page_size(provenance.get("page_number", 1))[1])
                if provenance.get("page_number", 1) == render["page"] and box and _holds(box, centre):
                    return element["id"]
        # A whole page, or a region no element holds: the case answers it as
        # ``page-<number>``.
        return f"page-{render['page']}"

    def _page_sizes(self) -> list[tuple[float, float]]:
        return [
            (float(page.get("width") or 612.0), float(page.get("height") or 792.0))
            for page in self.case["document"].get("pages") or [{}]
        ]

    def _page_size(self, number: int) -> tuple[float, float]:
        sizes = self._page_sizes()
        return sizes[number - 1] if 0 < number <= len(sizes) else (612.0, 792.0)


@contextlib.contextmanager
def installed(fake: FakeToolbox) -> Iterator[FakeToolbox]:
    """Route every ``httpx`` client created inside the block to ``fake``."""
    transport = httpx.MockTransport(fake.handle)
    originals = {cls: cls.__init__ for cls in (httpx.AsyncClient, httpx.Client)}

    def patched(original):
        def init(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("mounts", None)
            original(self, *args, **kwargs)
        return init

    for cls, original in originals.items():
        cls.__init__ = patched(original)  # type: ignore[method-assign]
    try:
        yield fake
    finally:
        for cls, original in originals.items():
            cls.__init__ = original  # type: ignore[method-assign]


class _Unanswerable(Exception):
    """The fake cannot answer this request from the case."""


def _form(request: httpx.Request) -> tuple[dict[str, str], dict[str, bytes]]:
    """The multipart (or urlencoded) form of ``request``: its fields and its files."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/x-www-form-urlencoded"):
        from urllib.parse import parse_qsl

        return dict(parse_qsl(request.content.decode())), {}
    if not content_type.startswith("multipart/"):
        return {}, {}
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + request.content
    )
    fields: dict[str, str] = {}
    files: dict[str, bytes] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            files[str(name)] = payload
        else:
            fields[str(name)] = payload.decode()
    return fields, files


def _latex(form: dict[str, str], files: dict[str, bytes]) -> str:
    """The LaTeX a ``math.*`` call sends: an uploaded ``formula.tex``, or a parameter."""
    if files:
        return next(iter(files.values())).decode("utf-8")
    parameters = json.loads(form.get("parameters") or "{}")
    return str(parameters.get("latex") or form.get("latex") or "")


def _succeeded(capability: str, provider: str, document: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={
        "status": "succeeded",
        "capability": capability,
        "provider": provider,
        "document": document,
        "provenance": {"duration_ms": 1, "provider_version": "differential-1"},
    })


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


def _solid_png(index: int) -> bytes:
    """A solid image whose colour encodes ``index`` (eight levels per channel)."""
    from PIL import Image

    levels = (index % 8, index // 8 % 8, index // 64 % 8)
    image = Image.new("RGB", (64, 64), tuple(16 + _STEP * level for level in levels))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _decode_index(content: bytes) -> int | None:
    """The index :func:`_solid_png` encoded, read from the image's centre."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        return None
    pixel = image.getpixel((image.width // 2, image.height // 2))
    levels = [round((channel - 16) / _STEP) for channel in pixel]  # type: ignore[union-attr]
    if any(level < 0 or level > 7 for level in levels):
        return None
    return levels[0] + 8 * levels[1] + 64 * levels[2]


def _box(value: Any, page_height: float | None = None) -> tuple[float, float, float, float] | None:
    """``(left, top, right, bottom)`` with y growing downwards."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    if isinstance(value, dict):
        left, top = float(value.get("left", 0)), float(value.get("top", 0))
        right, bottom = float(value.get("right", 0)), float(value.get("bottom", 0))
        origin = str(value.get("coord_origin") or value.get("origin") or "").upper()
        if origin == "BOTTOMLEFT" and page_height:
            top, bottom = page_height - top, page_height - bottom
        return (left, min(top, bottom), right, max(top, bottom))
    return None


def _holds(box: tuple[float, float, float, float], point: tuple[float, float]) -> bool:
    return box[0] - 1 <= point[0] <= box[2] + 1 and box[1] - 1 <= point[1] <= box[3] + 1


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _response_schema(body: dict[str, Any]) -> dict[str, Any] | None:
    response_format = body.get("response_format") or {}
    schema = (response_format.get("json_schema") or {}).get("schema")
    return schema if isinstance(schema, dict) else None


#: Values for fields the case does not answer, by name, when the schema's
#: type alone gives an invalid one.
_FIELD_DEFAULTS = {"language": "pt-BR", "confidence": 0.95, "description": "Visual content the case does not answer."}


def _instance(
    schema: dict[str, Any] | None,
    answers: dict[str, Any],
    defs: dict[str, Any] | None = None,
    name: str = "",
) -> Any:
    """A deterministic instance of ``schema``, with ``answers`` for its fields."""
    if schema is None:
        return answers.get("text", "")
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return _instance(defs[schema["$ref"].rsplit("/", 1)[-1]], answers, defs, name)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            if "default" in schema:
                return schema["default"]
            options = [option for option in schema[key] if option.get("type") != "null"]
            return _instance(options[0], answers, defs, name) if options else None
    kind = schema.get("type")
    if kind == "object":
        return {
            field: answers[field] if field in answers else _instance(spec, {}, defs, field)
            for field, spec in (schema.get("properties") or {}).items()
        }
    if name in _FIELD_DEFAULTS:
        return _FIELD_DEFAULTS[name]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if kind == "string":
        return "x" * int(schema.get("minLength", 0))
    if kind in {"number", "integer"}:
        return schema.get("minimum", 0)
    return {"boolean": False, "array": []}.get(kind)


__all__ = ["BASE_URL", "FakeToolbox", "installed"]
