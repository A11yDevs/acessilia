"""Method handlers of the PDDL pipeline, one module per group.

All are deterministic except ``inspection``, whose handlers ask the vision model.

``common`` holds what every handler shares; ``text`` repairs text in place;
``content`` checks or finishes an element's content; ``review`` escalates an
obligation to a person; ``fusion`` fuses the two providers of
``FUSION_MODE=dual`` or chooses between them, or confirms the single provider's
extraction; ``order`` reorders a page; ``inspection`` asks the vision agent
about a rendered region or page; ``formula`` converts, speaks and normalizes
the LaTeX of formula obligations through the Toolbox.
"""
