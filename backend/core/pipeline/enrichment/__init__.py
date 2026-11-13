"""Enrichment stages of the PDDL pipeline: the work done before planning.

``common`` holds what the picture and table stages share; ``pictures``
describes pictures with the vision model; ``tables`` reads tables with the data
agent; ``inline_math`` marks the math runs inside text and table cells;
``formulas`` classifies formula crops and reads their LaTeX (``math.recognize``,
then the vision model).
"""
