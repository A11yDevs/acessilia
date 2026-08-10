#!/usr/bin/env python3
import uvicorn

from backend.api.app import app
from backend.config.settings import settings


def main() -> None:
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
