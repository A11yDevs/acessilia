"""The PDDL pipeline of the core (#402, ADR-0016).

``orchestrator`` runs ``execute``; ``preflight``, ``payload``, ``toolbox``,
``elements``, ``obligations``, ``secondary`` and ``judge`` serve it, and
``enrichment/`` and ``handlers/`` hold its stages and method handlers. The
canonical document's modules gathered here from ``backend/pipeline`` (ADR-0016,
step 2): ``fusion`` (the dual-provider extraction), ``canonical_builder``,
``table_ast`` and ``validators`` (the bridges to docstruct's canonical
builder, table AST and validation, with the core's i18n).
"""
