"""Deterministic method handlers of the PDDL pipeline, one module per group.

``common`` holds what every handler shares; ``text`` repairs text in place;
``content`` checks or finishes an element's content; ``review`` escalates an
obligation to a person; ``fusion`` chooses between the two providers of
``FUSION_MODE=dual``, or confirms the single provider's extraction; ``order``
reorders a page.
"""
