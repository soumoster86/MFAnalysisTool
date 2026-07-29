"""Launch FastAPI with uvicorn."""

from __future__ import annotations

import uvicorn

from config.settings import settings


def main() -> None:
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
