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
from typing import Callable, List, Optional, Tuple

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
def _build_ssl_contexts() -> List[ssl.SSLContext]:
    """Lav en liste af SSL-kontekster vi vil prøve i rækkefølge.

    PyInstaller-byggede .exe'er på Windows mangler ofte CA-certifikater
    så ``ssl.create_default_context()`` fejler med
    ``CERTIFICATE_VERIFY_FAILED``. Vi prøver derfor flere strategier:

    1. Default context (Python's egen + systemets CA store)
    2. certifi's CA-bundle (hvis pakken er installeret/bundlet)
    3. truststore (Windows/macOS native cert store, hvis tilgængeligt)
    """
    contexts: List[ssl.SSLContext] = []

    # 1) Default — virker næsten altid på macOS/Linux og rene Python-installs
    try:
        contexts.append(ssl.create_default_context())
    except Exception:  # noqa: BLE001
        pass

    # 2) certifi — pålideligt CA-bundle uafhængigt af system
    try:
        import certifi  # type: ignore
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:  # noqa: BLE001
        pass

    # 2b) certifi-bundle pakket ind i PyInstaller (_MEIPASS/certifi/cacert.pem)
    try:
        if hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "certifi" / "cacert.pem"  # type: ignore[attr-defined]
            if bundled.exists():
                contexts.append(ssl.create_default_context(cafile=str(bundled)))
    except Exception:  # noqa: BLE001
        pass

    # 3) truststore — bruger OS' native cert-store (Windows/macOS keychain)
    try:
        import truststore  # type: ignore
        contexts.append(truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    except Exception:  # noqa: BLE001
        pass

    return contexts


# Sidste fejl fra _fetch_latest_release — så GUI kan vise hvorfor det fejlede
last_error: str = ""


def _fetch_latest_release(timeout: float = 8.0,
                          owner: str = GITHUB_OWNER,
                          repo: str = GITHUB_REPO) -> dict:
    """Hent rå JSON fra GitHub Releases API. Kaster ved netværksfejl.

    Prøver flere SSL-strategier hvis den første fejler (vigtigt for
    PyInstaller-bundles på Windows hvor CA-certifikater kan mangle).
    """
    global last_error
    url = _API_URL_TEMPLATE.format(owner=owner, repo=repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    })

    contexts = _build_ssl_contexts()
    if not contexts:
        last_error = "Kunne ikke oprette SSL-kontekst (Python uden ssl-modul?)"
        raise ssl.SSLError(last_error)

    last_exc: Optional[Exception] = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
            last_error = ""  # success — ryd evt. gammel fejl
            return json.loads(raw)
        except (urllib.error.URLError, ssl.SSLError) as e:
            last_exc = e
            # SSL-fejl? Prøv næste context. Andre fejl? Også prøv næste — kunne
            # være proxy-relateret hvor en anden SSL-strategi virker.
            continue
        except urllib.error.HTTPError:
            # HTTP-fejl (fx 404) — ikke et SSL-problem, kast videre
            raise

    # Alle kontekster fejlede — gem detaljen og kast den sidste exception
    if last_exc is not None:
        last_error = f"{type(last_exc).__name__}: {last_exc}"
        raise last_exc
    last_error = "Ukendt netværksfejl"
    raise urllib.error.URLError(last_error)


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

    Detaljeret fejlbesked kan læses fra modul-attributten ``last_error``
    efter et fejlet kald — nyttig til at vise meningsfuld besked til brugeren.
    """
    global last_error
    try:
        data = _fetch_latest_release(timeout=timeout, owner=owner, repo=repo)
    except urllib.error.HTTPError as e:
        # 404 = ingen releases endnu — behandl som "ingen ny version"
        if e.code == 404:
            last_error = ""
            return UpdateInfo(current=current, latest=current)
        last_error = f"HTTP {e.code}: {e.reason}"
        return None
    except urllib.error.URLError as e:
        last_error = f"Netværk: {e.reason}"
        return None
    except ssl.SSLError as e:
        last_error = f"SSL: {e}"
        return None
    except (TimeoutError, OSError) as e:
        last_error = f"{type(e).__name__}: {e}"
        return None
    except ValueError as e:
        last_error = f"Ugyldigt svar fra GitHub: {e}"
        return None

    last_error = ""
    return parse_release(data, current=current)


# ---------------------------------------------------------------------------
# Download + launch installer (rigtig in-app auto-update)
# ---------------------------------------------------------------------------
def default_download_dir() -> Path:
    """Hvor downloader vi installeren til?

    Vi bruger en under-mappe i temp så filen ikke ligger frit i Downloads,
    og så Windows automatisk rydder op senere. Opretter mappen hvis den
    ikke findes.
    """
    import tempfile
    d = Path(tempfile.gettempdir()) / "SetlistManagerUpdate"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # falder igennem — kalder må håndtere fejl ved download
    return d


def download_file(url: str,
                  dest_path: Path,
                  progress_callback: Optional[Callable[[int, int], None]] = None,
                  timeout: float = 30.0,
                  chunk_size: int = 64 * 1024) -> bool:
    """Hent en fil fra ``url`` og gem den til ``dest_path``.

    Bruger samme SSL-strategier som ``check_for_update`` så det også
    virker fra PyInstaller-bundles på Windows.

    progress_callback(bytes_downloaded, total_bytes) kaldes løbende.
    ``total_bytes`` kan være -1 hvis serveren ikke sender Content-Length.

    Returnerer True hvis det lykkedes, False ved fejl
    (læs ``last_error`` for detaljer).
    """
    global last_error
    if not url:
        last_error = "Tom URL"
        return False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".partial")

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    contexts = _build_ssl_contexts()
    if not contexts:
        last_error = "Ingen SSL-strategier tilgængelige"
        return False

    last_exc: Optional[Exception] = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                total = int(resp.headers.get("Content-Length", -1) or -1)
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            try:
                                progress_callback(downloaded, total)
                            except Exception:  # noqa: BLE001
                                pass  # progress-callback må aldrig crashe download
            # Atomisk rename så vi ikke ender med en halv fil ved fejl
            if dest_path.exists():
                dest_path.unlink()
            tmp_path.rename(dest_path)
            last_error = ""
            return True
        except (urllib.error.URLError, ssl.SSLError) as e:
            last_exc = e
            continue
        except (OSError, urllib.error.HTTPError) as e:
            last_error = f"{type(e).__name__}: {e}"
            # Ryd op
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return False

    if last_exc is not None:
        last_error = f"{type(last_exc).__name__}: {last_exc}"
    else:
        last_error = "Ukendt download-fejl"
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return False


def launch_installer(installer_path: Path, silent: bool = False) -> bool:
    """Start installeren og lad den overtage.

    På Windows: bruger ``os.startfile()`` som triggerer UAC-prompt korrekt.
    På macOS/Linux: kører den med subprocess (mest til tests — der er
    typisk ingen installer der at køre).

    Returnerer True hvis launch lykkedes (programmet kalder typisk
    ``sys.exit(0)`` umiddelbart efter så installeren kan overskrive filer).

    ``silent``: hvis True, prøv at køre Inno Setup i silent-mode
    (``/SILENT``) så brugeren ikke skal klikke Næste/Næste/Installér.
    """
    global last_error
    if not installer_path.exists():
        last_error = f"Filen findes ikke: {installer_path}"
        return False

    try:
        if sys.platform.startswith("win"):
            if silent:
                # Inno Setup understøtter /SILENT for at undgå klik
                # /CLOSEAPPLICATIONS: luk vores app hvis den stadig kører
                # /RESTARTAPPLICATIONS: start vores app igen efter installation
                import subprocess
                subprocess.Popen(
                    [
                        str(installer_path),
                        "/SILENT",
                        "/CLOSEAPPLICATIONS",
                        "/RESTARTAPPLICATIONS",
                    ],
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            else:
                # Normal mode — viser installer-wizard
                import os
                os.startfile(str(installer_path))  # type: ignore[attr-defined]
        else:
            # macOS/Linux: subprocess.Popen i detached mode
            import subprocess
            subprocess.Popen(
                [str(installer_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        last_error = ""
        return True
    except (OSError, ValueError) as e:
        last_error = f"Kunne ikke starte installeren: {e}"
        return False


def installer_filename_from_url(url: str, fallback: str = "SetlistManagerSetup.exe") -> str:
    """Trækker filnavnet ud af en download-URL.
    Fx 'https://.../SetlistManagerSetup-1.2.0.exe' → 'SetlistManagerSetup-1.2.0.exe'.
    """
    if not url:
        return fallback
    # Brug urlparse for at undgå query-strings
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path
        name = path.rsplit("/", 1)[-1]
        return name if name else fallback
    except Exception:  # noqa: BLE001
        return fallback
