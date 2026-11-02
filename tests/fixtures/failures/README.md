# Controlled-failure fixtures

Also available in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

Inert, intentionally broken documents used only to reproduce the
"pipeline failed" path without damaging a real file. They are checked in under
`tests/` and never referenced by production code, so they cannot be activated
by an upload in a running deployment.

| File | What is wrong with it |
|------|-----------------------|
| `empty.pdf` | A zero-byte file with a `.pdf` extension. |
| `not-a-pdf.pdf` | Plain text with a `.pdf` extension; no PDF structure at all. |
| `truncated.pdf` | A PDF header and a catalog object that references a missing `Pages` object, with no cross-reference table. |

They exercise the worker's failure branch (`backend/api/worker.py`,
`JobExecutor.run`) end to end: the real pipeline is handed the corrupt document,
aborts, and the user must still receive the failure e-mail
(`send_failure_email`).

## Running the scenario

No debug switch exists or is needed: the fixtures are ordinary files in the
test tree and the test is gated by the `e2e` marker, which CI excludes
(`pytest -m "not e2e"`). To run it against a real Toolbox:

```bash
TOOLBOX_BASE_URL=<url> uv run pytest -m e2e tests/test_job_failure_e2e.py -v
```

The test replaces only the SMTP transport with a recorder; the pipeline,
worker, job store and history are the real implementations. It asserts that the
job ends as `error`, that the output directory is removed, and that the failure
e-mail names the submitted file.

Unit coverage of the same branch (no Toolbox needed) lives in
`tests/test_job_progress.py` and `tests/test_email_service.py`.
