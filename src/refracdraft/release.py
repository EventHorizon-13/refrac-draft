from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
import re
import tomllib

from refracdraft.resources import resource_path


REPOSITORY = "EventHorizon-13/refrac-draft"
PROJECT_URL = f"https://github.com/{REPOSITORY}"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
_TAG = re.compile(r"standard-v(\d+)\.(\d+)\.(\d+)")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(b\d+)?")


def app_version() -> str:
    build_version = resource_path("assets/build-version.txt")
    if build_version.is_file():
        label = build_version.read_text(encoding="ascii").strip()
        if _VERSION.fullmatch(label):
            return label
    project_file = resource_path("pyproject.toml")
    if project_file.is_file():
        with project_file.open("rb") as project:
            return tomllib.load(project)["project"]["version"]
    try:
        return version("refrac-draft")
    except PackageNotFoundError:
        return "未知"


def build_time_display() -> str | None:
    try:
        timestamp = resource_path("assets/build-time.txt").read_text(encoding="ascii").strip()
        built_at = datetime.fromisoformat(timestamp)
    except (OSError, ValueError):
        return None
    return built_at.astimezone().strftime("%Y-%m-%d %H:%M:%S UTC%z")


def latest_portable_release(releases: list[dict]) -> tuple[str, str] | None:
    candidates = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        match = _TAG.fullmatch(tag)
        if not match:
            continue
        asset = f"RefracDraft-Standard-Windows-x64-portable-{tag.removeprefix('standard-')}.zip"
        if any(entry.get("name") == asset for entry in release.get("assets", ())):
            candidates.append((tuple(map(int, match.groups())), tag, asset))
    if not candidates:
        return None
    parts, tag, asset = max(candidates)
    current = _VERSION.fullmatch(app_version())
    if current is not None and (
        parts + (True,) <= tuple(map(int, current.groups()[:3])) + (current[4] is None,)
    ):
        return None
    return tag.removeprefix("standard-v"), f"{PROJECT_URL}/releases/download/{tag}/{asset}"
