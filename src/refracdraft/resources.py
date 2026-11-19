from __future__ import annotations

from pathlib import Path
import sys


def resource_path(relative: str) -> Path:
    """Locate tracked reference files in source or a PyInstaller one-folder bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parents[2] / relative


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return resource_path(".")

