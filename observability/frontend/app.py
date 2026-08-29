from __future__ import annotations

import os

import uvicorn

from observability.src.app import app, create_app


__all__ = ["app", "create_app"]


if __name__ == "__main__":
    uvicorn.run(
        "observability.src.app:app",
        host=os.getenv("OBSERVABILITY_FRONTEND_HOST", "127.0.0.1"),
        port=int(os.getenv("OBSERVABILITY_FRONTEND_PORT", "8010")),
        reload=os.getenv("OBSERVABILITY_FRONTEND_RELOAD", "false").lower() == "true",
    )

