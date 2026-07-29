"""Launch Streamlit UI from project root."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    app = ROOT / "frontend" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.headless",
        "true",
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)


if __name__ == "__main__":
    main()
