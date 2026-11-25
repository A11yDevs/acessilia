"""Enrichment stages of the PDDL pipeline: the pictures' preparation before
planning, and the stages the ``formula-region-classifier``,
``picture-description``, ``formula-recognizer``, ``table-enrichment`` and
``inline-math-marker`` methods run inside the plan (#640, M4a, M1, M3, M2
and M4b).

``common`` holds what the picture and table stages share; ``pictures``
describes pictures with the vision model; ``tables`` reads tables with the data
agent; ``inline_math`` marks the math runs inside text and table cells;
``formulas`` classifies formula crops and reads their LaTeX (``math.recognize``,
then the vision model).
"""
