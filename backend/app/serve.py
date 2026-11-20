"""Uvicorn launcher that delegates forwarding trust to OpsDesk middleware."""

import uvicorn

from app.core.config import settings


def get_uvicorn_options() -> dict:
    return {
        "host": settings.host,
        "port": settings.port,
        "reload": settings.app_env not in {"production", "prod"},
        # Avoid Uvicorn rewriting scope['client'] using its own proxy defaults.
        "proxy_headers": False,
    }


def main() -> None:
    uvicorn.run("app.main:app", **get_uvicorn_options())


if __name__ == "__main__":
    main()
