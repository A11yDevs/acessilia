"""Benchmark adapters, by CLI name."""

from scripts.bench.datasets.base import BenchPage, Dataset
from scripts.bench.datasets.drdocbench import DrDocBench

DATASETS: dict[str, Dataset] = {d.name: d for d in (DrDocBench(),)}

__all__ = ["DATASETS", "BenchPage", "Dataset"]
