import os
import time

from backend.config.settings import settings
from backend.services.cleanup_service import _clean_output_directory


def _create_aged_output(output_dir, name, age_seconds):
    job_dir = output_dir / name
    job_dir.mkdir(parents=True)
    result = job_dir / "resultado.txt"
    result.write_text("resultado", encoding="utf-8")
    timestamp = time.time() - age_seconds
    os.utime(result, (timestamp, timestamp))
    os.utime(job_dir, (timestamp, timestamp))
    return job_dir


def test_output_cleanup_keeps_results_younger_than_seven_days(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    output_dir = tmp_path / "output"
    job_dir = _create_aged_output(output_dir, "job-recente", 25 * 60 * 60)

    _clean_output_directory()

    assert job_dir.exists()


def test_output_cleanup_removes_results_older_than_seven_days(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    output_dir = tmp_path / "output"
    job_dir = _create_aged_output(output_dir, "job-expirado", 8 * 24 * 60 * 60)

    _clean_output_directory()

    assert not job_dir.exists()
