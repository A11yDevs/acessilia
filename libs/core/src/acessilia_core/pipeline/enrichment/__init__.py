"""Enrichment stages of the PDDL pipeline: the work done before planning, and
the stages the ``picture-description``, ``formula-recognizer`` and
``table-enrichment`` methods run inside the plan (#640, M1, M3 and M2).

``common`` holds what the picture and table stages share; ``pictures``
describes pictures with the vision model; ``tables`` reads tables with the data
agent; ``inline_math`` marks the math runs inside text and table cells;
``formulas`` classifies formula crops and reads their LaTeX (``math.recognize``,
then the vision model).
"""
