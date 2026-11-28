from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
import re
import tomllib
from urllib.parse import urlsplit

from refracdraft.resources import resource_path


REPOSITORY = "EventHorizon-13/refrac-draft"
PROJECT_URL = f"https://github.com/{REPOSITORY}"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
RELEASES_URL = f"{PROJECT_URL}/releases"
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
        asset = _portable_asset(tag)
        if any(entry.get("name") == asset for entry in release.get("assets", ())):
            candidates.append((tuple(map(int, match.groups())), tag))
    if not candidates:
        return None
    _parts, tag = max(candidates)
    return _newer_portable_release(tag)


def _portable_asset(tag: str) -> str:
    return f"RefracDraft-Standard-Windows-x64-portable-{tag.removeprefix('standard-')}.zip"


def portable_release_from_latest_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    prefix = f"/{REPOSITORY}/releases/tag/"
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(prefix):
        raise ValueError("未找到标准版正式发布")
    return _newer_portable_release(parsed.path.removeprefix(prefix))


def _newer_portable_release(tag: str) -> tuple[str, str] | None:
    match = _TAG.fullmatch(tag)
    if not match:
        raise ValueError("未找到标准版正式发布")
    parts = tuple(map(int, match.groups()))
    current = _VERSION.fullmatch(app_version())
    if current is not None and (
        parts + (True,) <= tuple(map(int, current.groups()[:3])) + (current[4] is None,)
    ):
        return None
    return tag.removeprefix("standard-v"), f"{RELEASES_URL}/download/{tag}/{_portable_asset(tag)}"
