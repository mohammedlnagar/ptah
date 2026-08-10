#!/usr/bin/env python
"""Create a private local Django environment file without exposing its secret."""

from __future__ import annotations

import secrets
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def main() -> None:
    if ENV_PATH.exists():
        raise SystemExit(f"{ENV_PATH} already exists; refusing to overwrite it.")

    values = {
        "SECRET_KEY": secrets.token_urlsafe(64),
        "SECRET_KEY_FALLBACKS": "",
        "DEBUG": "True",
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DATABASE_URL": "",
        "TIME_ZONE": "Asia/Dubai",
    }
    content = "".join(f"{key}={value}\n" for key, value in values.items())
    ENV_PATH.write_text(content, encoding="utf-8", newline="\n")

    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass

    print(f"Created {ENV_PATH}. The generated secret was not printed.")


if __name__ == "__main__":
    main()
