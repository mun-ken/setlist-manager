"""Setlist Manager — opslag i MusicBrainz (gratis musikdatabase).

Vi bruger MusicBrainz fordi:
 - Det er gratis og kræver ingen API-nøgle
 - Det dækker næsten alle udgivne bands - også danske som D-A-D,
   Magtens Korridorer, Volbeat, Kim Larsen osv.
 - Det giver os både sangtitler OG længder
 - Standardbiblioteket (urllib) kan tale med det - ingen ekstra dependencies

Vi følger MusicBrainz' regler ved at sende en User-Agent og holde os
til max 1 forespørgsel pr. sekund.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

USER_AGENT = "SetlistManager/1.0 ( https://github.com/setlistmanager )"
BASE_URL = "https://musicbrainz.org/ws/2"
NETWORK_TIMEOUT = 15  # sekunder pr. forespørgsel
RATE_LIMIT_DELAY = 1.0  # sekunder mellem forespørgsler (MusicBrainz' regel)


class MusicSearchError(Exception):
    """Generisk fejl ved netværksopslag."""


# ---------------------------------------------------------------------------
# Lavt niveau: HTTP
# ---------------------------------------------------------------------------
def _http_get_json(url: str) -> Dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 503:
            raise MusicSearchError(
                "MusicBrainz er overbelastet lige nu. Prøv igen om et øjeblik."
            ) from e
        raise MusicSearchError(f"Serverfejl ({e.code}) fra MusicBrainz.") from e
    except urllib.error.URLError as e:
        raise MusicSearchError(
            "Kunne ikke kontakte MusicBrainz.\n"
            "Tjek din internetforbindelse og prøv igen."
        ) from e
    except TimeoutError as e:
        raise MusicSearchError("Forespørgslen tog for lang tid.") from e

    try:
        return json.loads(raw)
    except ValueError as e:
        raise MusicSearchError("Uventet svar fra MusicBrainz.") from e


# ---------------------------------------------------------------------------
# Trin 1: find bandet
# ---------------------------------------------------------------------------
def search_artists(name: str, limit: int = 15) -> List[Dict]:
    """Find bands der matcher `name`.

    Returnerer en liste sorteret efter MusicBrainz-score (bedste match først).
    Hvert element:
       {"id", "name", "country", "disambiguation", "type", "score"}
    """
    name = (name or "").strip()
    if not name:
        return []
    q = urllib.parse.quote(name)
    url = f"{BASE_URL}/artist/?query={q}&fmt=json&limit={limit}"
    data = _http_get_json(url)

    results: List[Dict] = []
    for a in data.get("artists", []):
        results.append(
            {
                "id": a.get("id", ""),
                "name": a.get("name", ""),
                "country": a.get("country", "") or "",
                "disambiguation": a.get("disambiguation", "") or "",
                "type": a.get("type", "") or "",
                "score": int(a.get("score", 0) or 0),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Trin 2: hent alle sange
# ---------------------------------------------------------------------------
def fetch_recordings(
    artist_mbid: str,
    max_total: int = 1000,
    progress_callback=None,
) -> List[Dict]:
    """Hent alle unikke sange (recordings) for et band.

    `progress_callback(fetched, total)` kaldes løbende, hvis givet.

    Returnerer en liste af:
        {"title": str, "duration_seconds": int or None, "duration": "m:ss" or ""}
    sorteret alfabetisk og dedupliceret.
    """
    if not artist_mbid:
        return []

    seen: Dict[str, Dict] = {}
    offset = 0
    page = 100
    total_count = None
    is_first = True

    while offset < max_total:
        if not is_first:
            time.sleep(RATE_LIMIT_DELAY)
        is_first = False

        url = (
            f"{BASE_URL}/recording/?artist={artist_mbid}"
            f"&fmt=json&limit={page}&offset={offset}"
        )
        try:
            data = _http_get_json(url)
        except MusicSearchError:
            if not seen:
                raise
            break  # vi har i hvert fald noget - returnér det

        recordings = data.get("recordings", [])
        if total_count is None:
            total_count = int(data.get("recording-count", len(recordings)) or 0)

        if not recordings:
            break

        for r in recordings:
            title = (r.get("title") or "").strip()
            if not title:
                continue
            key = title.casefold()
            length_ms = r.get("length")
            duration_seconds = int(length_ms) // 1000 if length_ms else None

            existing = seen.get(key)
            if existing is None:
                seen[key] = _make_recording(title, duration_seconds)
            elif existing["duration_seconds"] is None and duration_seconds:
                # Foretræk versionen med kendt længde
                seen[key] = _make_recording(title, duration_seconds)

        offset += page
        if progress_callback:
            try:
                progress_callback(min(offset, total_count or offset), total_count or offset)
            except Exception:
                pass
        if total_count is not None and offset >= total_count:
            break

    return sorted(seen.values(), key=lambda x: x["title"].casefold())


def _make_recording(title: str, duration_seconds: Optional[int]) -> Dict:
    return {
        "title": title,
        "duration_seconds": duration_seconds,
        "duration": format_duration(duration_seconds),
    }


# ---------------------------------------------------------------------------
# Hjælpere
# ---------------------------------------------------------------------------
def format_duration(seconds: Optional[int]) -> str:
    """Formatér sekunder som 'm:ss' eller 'h:mm:ss'. Tom string ved None/0."""
    if not seconds or seconds <= 0:
        return ""
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_artist_label(artist: Dict) -> str:
    """Lav en pæn label til visning i listen, fx 'D-A-D (DK) - rock group'."""
    parts = [artist.get("name", "(uden navn)")]
    extras: List[str] = []
    if artist.get("country"):
        extras.append(artist["country"])
    if artist.get("type"):
        extras.append(artist["type"])
    if artist.get("disambiguation"):
        extras.append(artist["disambiguation"])
    if extras:
        parts.append(" — " + " · ".join(extras))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Live-version detektion
# ---------------------------------------------------------------------------
# Matcher:
#   "Song (Live)"            "Song (Live at Wembley)"   "Song [Live]"
#   "Song - Live"            "Song – Live in Tokyo"      "Song (Live Version)"
# Matcher IKKE:
#   "Live and Let Die"   (Live er ikke i parens/brackets eller efter en dash)
#   "Live at the BBC"    (samme grund)
#   "Aliveness"          (\b kræver ord-grænse - 'live' inde i 'aliveness' tæller ikke)
_LIVE_PATTERN = re.compile(
    r"[\(\[][^)\]]*\blive\b[^)\]]*[\)\]]"   # (Live...), [Live...]
    r"|"
    r"[-\u2013\u2014]\s*\blive\b",          # - Live, – Live, — Live
    re.IGNORECASE,
)


def is_live_version(title: str) -> bool:
    """Returnerer True hvis sangtitlen indikerer at det er en live-version."""
    if not title:
        return False
    return bool(_LIVE_PATTERN.search(title))


def filter_out_live(recordings: List[Dict]) -> List[Dict]:
    """Returnerer en ny liste uden live-versioner."""
    return [r for r in recordings if not is_live_version(r.get("title", ""))]
