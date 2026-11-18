"""Deterministic exporters built on the canonical accessible document model.

Gathered here from ``backend/export`` (ADR-0016, step 2): ``exporters/``
(TXT, DOCX, PDF/UA, MP3, DrBench Markdown), ``renderers/`` (HTML and TXT),
``pandoc_exporter`` (the audited export to each format; DOCX and PDF/UA are
rendered by the Toolbox), ``markers`` (the object markers' labels) and
``messages`` (the export's msgids: the default title and the export errors).
"""
