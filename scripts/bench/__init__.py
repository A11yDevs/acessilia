"""Benchmark harness: run the core on a document-parsing dataset and score it.

Datasets plug in through ``scripts.bench.datasets`` (one adapter per
benchmark); the metrics and the markdown serialization live in docstruct, so
every dataset is scored the same way. Usage: ``python -m scripts.bench --help``.
"""
