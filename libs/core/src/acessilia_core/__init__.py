"""Acessilia's core: the PDDL pipeline that plans and executes a document's
accessibility (ADR-0016).

It imports nothing from the service (``backend``) or the front ends
(``frontend``) and reads no environment variable: its caller passes a
``CoreConfig``, the run's ``RunPorts`` and the model-call runner, and sets up
the process once (the logger and the locales).
"""

#: Kept equal to ``project.version`` in ``libs/core/pyproject.toml``; a test checks it.
__version__ = "0.3.18"
