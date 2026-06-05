"""Online opdaterings-tjek mod GitHub Releases.

Bruger kun Python stdlib — ingen ekstra afhængigheder. Køres typisk
i en baggrundstråd så GUI ikke fryser. Cache er gemt i
%APPDATA%/SetlistManager/last_update_check.json (Windows) eller
~/.config/SetlistManager/last_update_check.json (mac/Linux) så vi
ikke spammer GitHub-API'et.

Eksempler::

    info = check_for_update(timeout=8)
    if info and info.is_newer:
        print(f"Ny version: {info.latest}")
        print(f"Download: {info.installer_url or info.release_url}")
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

_USER_AGENT = f"SetlistManager/{APP_VERSION} (+update-check)"
_API_URL_TEMPLATE = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
_CACHE_FILE = "last_update_check.json"
_AUTO_CHECK_INTERVAL_HOURS = 24  # Spørg højst én gang pr. døgn


# ---------------------------------------------------------------------------
# Version parsing + sammenligning (semver — uden ekstra afhængigheder)
# ---------------------------------------------------------------------------
_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(s: str) -> Tuple[int, int, int]:
    """Parse en version-string som '1.2.3' eller 'v1.2' til en tuple.

    Robust over for prefix 'v', manglende patch/minor, og ekstra suffix
    (fx '1.2.3-beta' → (1, 2, 3)). Returnerer (0, 0, 0) hvis intet match.
    """
    if not s:
        return (0, 0, 0)
    m = _VERSION_RE.match(str(s).strip())
    if not m:
        return (0, 0, 0)
    return (
        int(m.group(1) or 0),
        int(m.group(2) or 0),
        int(m.group(3) or 0),
    )


def is_newer(latest: str, current: str) -> bool:
    """True hvis `latest` er en højere version end `current`."""
    return parse_version(latest) > parse_version(current)


# ---------------------------------------------------------------------------
# UpdateInfo — resultatet af et tjek
# ---------------------------------------------------------------------------
@dataclass
class UpdateInfo:
    """Information om den nyeste release fundet på GitHub."""

    current: str
    latest: str
    release_url: str = ""       # Browser-URL til release-siden
    installer_url: str = ""     # Direkte download (SetlistManagerSetup.exe)
    body: str = ""              # Release-noter (markdown)
    published_at: str = ""      # ISO 8601 dato
    assets: List[str] = field(default_factory=list)

    @property
    def is_newer(self) -> bool:
        return is_newer(self.latest, self.current)


# ---------------------------------------------------------------------------
# Cache (rate limiting)
# ---------------------------------------------------------------------------
def _cache_dir() -> Path:
    if sys.platform.startswith("win"):
        import os
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "SetlistManager"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SetlistManager"
    return Path.home() / ".config" / "SetlistManager"


def _cache_path() -> Path:
    return _cache_dir() / _CACHE_FILE


def load_cache() -> dict:
    """Hent cache-filens indhold. Tom dict hvis den ikke findes/er korrupt."""
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(data: dict) -> bool:
    """Skriv cache. Returnerer False ved fejl (men crasher ikke)."""
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def should_auto_check(now: Optional[float] = None,
                     interval_hours: int = _AUTO_CHECK_INTERVAL_HOURS) -> bool:
    """True hvis det er tid til et nyt auto-tjek (baseret på cache)."""
    if now is None:
        now = time.time()
    cache = load_cache()
    last = cache.get("last_check_ts", 0)
    try:
        last = float(last)
    except (TypeError, ValueError):
        last = 0.0
    return (now - last) >= (interval_hours * 3600)


def mark_checked(now: Optional[float] = None, info: Optional[UpdateInfo] = None) -> None:
    """Opdater cache med tidspunkt + evt. seneste version vi har set."""
    if now is None:
        now = time.time()
    cache = load_cache()
    cache["last_check_ts"] = now
    cache["last_check_iso"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    if info is not None:
        cache["latest_seen"] = info.latest
        if info.is_newer:
            cache["latest_newer_than"] = info.current
    save_cache(cache)


def mark_skipped(version: str) -> None:
    """Husk at brugeren har valgt at springe denne version over."""
    cache = load_cache()
    cache["skipped_version"] = version
    save_cache(cache)


def is_skipped(version: str) -> bool:
    """True hvis brugeren har bedt om at springe denne version over."""
    return load_cache().get("skipped_version") == version


# ---------------------------------------------------------------------------
# Selve API-kaldet
# ---------------------------------------------------------------------------
def _fetch_latest_release(timeout: float = 8.0,
                          owner: str = GITHUB_OWNER,
                          repo: str = GITHUB_REPO) -> dict:
    """Hent rå JSON fra GitHub Releases API. Kaster ved netværksfejl."""
    url = _API_URL_TEMPLATE.format(owner=owner, repo=repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    # Brug systemets default CA-bundle (vigtigt for at undgå SSL-fejl)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def parse_release(data: dict, current: str = APP_VERSION) -> UpdateInfo:
    """Parse GitHub's release-JSON til en UpdateInfo. Tom hvis data er ugyldig."""
    if not isinstance(data, dict):
        return UpdateInfo(current=current, latest="0.0.0")

    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    release_url = str(data.get("html_url") or "")
    body = str(data.get("body") or "")
    published = str(data.get("published_at") or "")

    installer_url = ""
    asset_names: List[str] = []
    for asset in data.get("assets", []) or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not name or not url:
            continue
        asset_names.append(name)
        # Foretræk installeren — fallback til standalone .exe
        lower = name.lower()
        if "setup" in lower and lower.endswith(".exe"):
            installer_url = url
        elif not installer_url and lower.endswith(".exe"):
            installer_url = url

    return UpdateInfo(
        current=current,
        latest=tag or "0.0.0",
        release_url=release_url,
        installer_url=installer_url,
        body=body,
        published_at=published,
        assets=asset_names,
    )


def check_for_update(timeout: float = 8.0,
                     current: str = APP_VERSION,
                     owner: str = GITHUB_OWNER,
                     repo: str = GITHUB_REPO) -> Optional[UpdateInfo]:
    """Tjek GitHub Releases for en nyere version.

    Returnerer altid en UpdateInfo (med ``is_newer`` flag) hvis tjekket
    lykkedes, ellers None ved netværksfejl. Crasher aldrig.
    """
    try:
        data = _fetch_latest_release(timeout=timeout, owner=owner, repo=repo)
    except urllib.error.HTTPError as e:
        # 404 = ingen releases endnu — behandl som "ingen ny version"
        if e.code == 404:
            return UpdateInfo(current=current, latest=current)
        return None
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError, ValueError):
        return None

    return parse_release(data, current=current)
