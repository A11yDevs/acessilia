"""Per-job capability authorization for anonymous submissions."""

from secrets import compare_digest

from fastapi import Header, HTTPException

from backend.services.job_store import load_record, token_digest


def require_job_access(task_id: str, x_job_token: str | None = Header(None)) -> None:
    record = load_record(task_id)
    if (
        not record
        or not x_job_token
        or not compare_digest(token_digest(x_job_token), record["token_hash"])
    ):
        raise HTTPException(status_code=404, detail="Job not found")
