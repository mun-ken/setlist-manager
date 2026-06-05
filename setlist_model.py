"""Setlist Manager — data model med multi-band support.

Schema v3 (current)
-------------------
{
  "schema_version": 3,
  "bands": [
    {
      "name": str,
      "library": [{"name", "key", "duration", "notes"}, ...],
      "setlists": [{"name", "songs": [str, ...], "modified_at": ISO-string}, ...],
      "active_setlist": int
    }, ...
  ],
  "active_band": int,
  "print_options": {
    "show_number": bool, "show_key": bool, "show_duration": bool,
    "show_notes": bool, "show_total_time": bool
  }
}

Schema v2 (auto-migrated): {schema_version: 2, library, setlists, active_setlist}
  → vikles ind i ét enkelt band kaldet "Mit band".

Schema v1 (auto-migrated): {library: [str], setlist: [str]}
  → migreres til ét band med én setliste.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "SetlistManager"
    return Path.home() / ".setlist_manager"


def default_autosave_path() -> Path:
    return default_data_dir() / "autosave.json"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
def new_song(name, duration="", key="", notes="") -> Dict:
    return {
        "name": (name or "").strip(),
        "key": (key or "").strip(),
        "duration": (duration or "").strip(),
        "notes": (notes or "").strip(),
    }


def new_setlist(name="Ny setliste") -> Dict:
    return {
        "name": (name or "Setliste").strip() or "Setliste",
        "songs": [],
        # ISO 8601 timestamp (UTC) — opdateres hver gang setlisten ændres
        "modified_at": _now_iso(),
    }


def _now_iso() -> str:
    """Aktuel tid som ISO 8601 string i UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_band(name="Mit band") -> Dict:
    return {
        "name": (name or "Mit band").strip() or "Mit band",
        "library": [],
        "setlists": [new_setlist("Min første setliste")],
        "active_setlist": 0,
        "logo_base64": "",  # data URL eller tom string
    }


# ---------------------------------------------------------------------------
# Setlist-item helpers — et item er enten en str (sangnavn) eller en
# dict {"marker": "Label"} for en sektion-markør (fx "Ekstra-nummer").
# ---------------------------------------------------------------------------
def is_marker_item(item) -> bool:
    """True hvis item er en sektion-markør (dict med 'marker' key)."""
    return isinstance(item, dict) and "marker" in item


def item_song_name(item) -> str:
    """Returnerer sangnavn hvis item er en sang, ellers tom string."""
    if isinstance(item, str):
        return item
    return ""


def item_marker_label(item) -> str:
    """Returnerer markør-label hvis item er en markør, ellers tom string."""
    if isinstance(item, dict):
        return str(item.get("marker", "")).strip()
    return ""


def make_marker(label: str) -> Dict:
    """Lav et nyt markør-item."""
    return {"marker": (label or "").strip() or "—"}


def default_print_options() -> Dict:
    return {
        # Header
        "show_title": True,
        "show_meta": True,
        "show_date": True,
        "show_logo": True,
        # Tabel
        "show_table_header": True,
        "show_number": True,
        "show_key": True,
        "show_duration": True,
        "show_notes": True,
        # Footer + sektioner
        "show_total_time": True,
        "show_markers": True,
        # Tekststørrelse
        "font_size": "medium",  # "xsmall" | "small" | "medium" | "large" | "xlarge"
    }


# Tekststørrelser brugt i print HTML (pt) — én pr. tekstklasse
FONT_SIZES_PT = {
    "xsmall": {"title": 18, "meta": 8,  "table":  9, "notes":  8, "total":  9},
    "small":  {"title": 22, "meta": 9,  "table": 11, "notes": 10, "total": 10},
    "medium": {"title": 28, "meta": 10, "table": 14, "notes": 12, "total": 12},
    "large":  {"title": 34, "meta": 11, "table": 18, "notes": 15, "total": 14},
    "xlarge": {"title": 42, "meta": 12, "table": 22, "notes": 18, "total": 16},
}


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------
def parse_duration(s) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(s)
    except ValueError:
        return 0


def format_seconds(secs) -> str:
    if secs is None or secs < 0:
        secs = 0
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# Danske månedsnavne — bruges af format_modified_at()
_DK_MONTHS = (
    "januar", "februar", "marts", "april", "maj", "juni",
    "juli", "august", "september", "oktober", "november", "december",
)


def format_modified_at(iso_string: str, now: Optional[datetime] = None) -> str:
    """Lav et ISO 8601 timestamp om til pænt dansk format.

    Eksempler:
        ""                        → ""           (ukendt)
        "2026-06-05T22:10:00+00:00" hvis lige nu → "i dag kl. 22:10"
        "2026-06-04T22:10:00+00:00"  → "i går kl. 22:10"
        "2026-05-30T10:00:00+00:00"  → "30. maj kl. 10:00"
        "2024-03-15T10:00:00+00:00"  → "15. marts 2024 kl. 10:00"
    """
    if not iso_string:
        return ""
    try:
        dt = datetime.fromisoformat(iso_string)
    except (TypeError, ValueError):
        return ""
    # Konverter til lokal tid hvis vi har timezone-info
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    now = now or datetime.now(dt.tzinfo) if dt.tzinfo else (now or datetime.now())
    today = now.date()
    when = dt.date()
    time_part = f"kl. {dt:%H:%M}"
    if when == today:
        return f"i dag {time_part}"
    if (today - when).days == 1:
        return f"i går {time_part}"
    month = _DK_MONTHS[dt.month - 1]
    if dt.year == now.year:
        return f"{dt.day}. {month} {time_part}"
    return f"{dt.day}. {month} {dt.year} {time_part}"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class SetlistModel:
    def __init__(self) -> None:
        self.bands: List[Dict] = [new_band("Mit band")]
        self.active_band: int = 0
        self.print_options: Dict = default_print_options()

    # ------------------------------------------------------------------
    # Backwards-compatible proxies — these let v2-era code keep working,
    # because self.library / self.setlists / self.active_setlist all
    # operate on the CURRENT band transparently.
    # ------------------------------------------------------------------
    @property
    def current_band(self) -> Dict:
        if not self.bands:
            self.bands = [new_band()]
            self.active_band = 0
        if self.active_band < 0 or self.active_band >= len(self.bands):
            self.active_band = 0
        return self.bands[self.active_band]

    @property
    def library(self) -> List[Dict]:
        return self.current_band["library"]

    @library.setter
    def library(self, value: List[Dict]) -> None:
        self.current_band["library"] = value

    @property
    def setlists(self) -> List[Dict]:
        return self.current_band["setlists"]

    @setlists.setter
    def setlists(self, value: List[Dict]) -> None:
        self.current_band["setlists"] = value

    @property
    def active_setlist(self) -> int:
        return self.current_band["active_setlist"]

    @active_setlist.setter
    def active_setlist(self, value: int) -> None:
        self.current_band["active_setlist"] = value

    @property
    def current_setlist(self) -> Dict:
        band = self.current_band
        if not band["setlists"]:
            band["setlists"] = [new_setlist()]
            band["active_setlist"] = 0
        idx = band["active_setlist"]
        if idx < 0 or idx >= len(band["setlists"]):
            band["active_setlist"] = 0
            idx = 0
        return band["setlists"][idx]

    # ------------------------------------------------------------------
    # Bands
    # ------------------------------------------------------------------
    def band_names(self) -> List[str]:
        return [b["name"] for b in self.bands]

    def add_band(self, name: str = "Nyt band") -> int:
        self.bands.append(new_band(name))
        self.active_band = len(self.bands) - 1
        return self.active_band

    def delete_band(self, idx: int) -> bool:
        if 0 <= idx < len(self.bands) and len(self.bands) > 1:
            del self.bands[idx]
            if self.active_band >= len(self.bands):
                self.active_band = len(self.bands) - 1
            return True
        return False

    def rename_band(self, idx: int, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        if 0 <= idx < len(self.bands):
            self.bands[idx]["name"] = name
            return True
        return False

    def set_active_band(self, idx: int) -> None:
        if 0 <= idx < len(self.bands):
            self.active_band = idx

    # ------------------------------------------------------------------
    # Songs (within current band's library)
    # ------------------------------------------------------------------
    def song_names(self) -> List[str]:
        return [s["name"] for s in self.library]

    def get_song(self, name: str) -> Optional[Dict]:
        for s in self.library:
            if s["name"] == name:
                return s
        return None

    def add_song(self, name, duration="", key="", notes="") -> bool:
        name = (name or "").strip()
        if not name or self.get_song(name) is not None:
            return False
        self.library.append(new_song(name, duration, key, notes))
        return True

    def update_song(self, original_name, name, duration, key, notes) -> bool:
        song = self.get_song(original_name)
        if song is None:
            return False
        new_name = (name or "").strip()
        if not new_name:
            return False
        if new_name != original_name and self.get_song(new_name) is not None:
            return False
        song["name"] = new_name
        song["key"] = (key or "").strip()
        song["duration"] = (duration or "").strip()
        song["notes"] = (notes or "").strip()
        if new_name != original_name:
            for sl_idx, sl in enumerate(self.setlists):
                if any(n == original_name for n in sl["songs"] if isinstance(n, str)):
                    sl["songs"] = [new_name if n == original_name else n for n in sl["songs"]]
                    self.touch_setlist(sl_idx)
        return True

    def remove_song_by_index(self, idx: int) -> None:
        if 0 <= idx < len(self.library):
            removed = self.library.pop(idx)
            removed_name = removed["name"]
            for sl_idx, sl in enumerate(self.setlists):
                before = len(sl["songs"])
                sl["songs"] = [n for n in sl["songs"] if n != removed_name]
                if len(sl["songs"]) != before:
                    self.touch_setlist(sl_idx)

    def clear_library(self) -> None:
        self.library.clear()
        for sl_idx, sl in enumerate(self.setlists):
            if sl["songs"]:
                sl["songs"] = []
                self.touch_setlist(sl_idx)

    # ------------------------------------------------------------------
    # Setlists (within current band)
    # ------------------------------------------------------------------
    def add_setlist(self, name="Ny setliste") -> int:
        self.setlists.append(new_setlist(name))
        self.active_setlist = len(self.setlists) - 1
        return self.active_setlist

    def duplicate_setlist(self, idx: int, new_name: Optional[str] = None) -> int:
        """Lav en kopi af setlisten ved index. Returnerer index for den nye
        kopi, eller -1 hvis index er ugyldigt.

        Sange er strings (immutable), markører er dicts (skal deep-kopieres).
        Den nye setliste får automatisk navn "<original> (kopi)" hvis
        ``new_name`` ikke er givet, og bliver den aktive setliste.
        """
        if not (0 <= idx < len(self.setlists)):
            return -1
        src = self.setlists[idx]
        # Deep-copy songs: strings er immutable, markører (dicts) skal kopieres
        copied_songs = []
        for item in src.get("songs", []):
            if isinstance(item, dict):
                copied_songs.append(dict(item))  # shallow copy af dict er nok
            else:
                copied_songs.append(item)
        copy_name = (new_name or "").strip() or f"{src['name']} (kopi)"
        new_sl = {
            "name": copy_name,
            "songs": copied_songs,
            "modified_at": _now_iso(),
        }
        # Indsæt lige efter originalen så de står ved siden af hinanden
        insert_at = idx + 1
        self.setlists.insert(insert_at, new_sl)
        self.active_setlist = insert_at
        return insert_at

    def delete_setlist(self, idx: int) -> bool:
        if 0 <= idx < len(self.setlists) and len(self.setlists) > 1:
            del self.setlists[idx]
            if self.active_setlist >= len(self.setlists):
                self.active_setlist = len(self.setlists) - 1
            return True
        return False

    def rename_setlist(self, idx: int, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        if 0 <= idx < len(self.setlists):
            self.setlists[idx]["name"] = name
            self.setlists[idx]["modified_at"] = _now_iso()
            return True
        return False

    def set_active(self, idx: int) -> None:
        if 0 <= idx < len(self.setlists):
            self.active_setlist = idx

    def touch_setlist(self, idx: Optional[int] = None) -> None:
        """Marker en setliste som ændret nu (opdaterer modified_at).
        Hvis idx er None bruges den aktive setliste."""
        if idx is None:
            idx = self.active_setlist
        if 0 <= idx < len(self.setlists):
            self.setlists[idx]["modified_at"] = _now_iso()

    def get_setlist_modified_at(self, idx: Optional[int] = None) -> str:
        """Returnerer ISO-timestamp for hvornår setlisten sidst blev ændret,
        eller tom string hvis den aldrig er blevet markeret som ændret
        (typisk for setlister importeret fra gamle gem-filer)."""
        if idx is None:
            idx = self.active_setlist
        if 0 <= idx < len(self.setlists):
            return str(self.setlists[idx].get("modified_at", ""))
        return ""

    # ------------------------------------------------------------------
    # Songs in current setlist
    # ------------------------------------------------------------------
    def is_in_current_setlist(self, name: str) -> bool:
        """True hvis sangen allerede ligger i den aktive setliste."""
        if not name:
            return False
        return any(item_song_name(it) == name for it in self.current_setlist["songs"])

    def add_to_setlist_by_index(self, lib_idx: int) -> bool:
        """Tilføj sang ved bibliotek-index. Returnerer True hvis tilføjet,
        False hvis index er ugyldig eller sangen allerede er i setlisten."""
        if not (0 <= lib_idx < len(self.library)):
            return False
        name = self.library[lib_idx]["name"]
        if self.is_in_current_setlist(name):
            return False
        self.current_setlist["songs"].append(name)
        self.touch_setlist()
        return True

    def add_marker_to_setlist(self, label: str, position: Optional[int] = None) -> int:
        """Indsæt en sektion-markør (fx 'Ekstra-nummer') i setlisten.
        Hvis position er None, append til enden — ellers insert FØR position.
        Returnerer det nye index, eller -1 hvis label er tom."""
        label = (label or "").strip()
        if not label:
            return -1
        songs = self.current_setlist["songs"]
        item = make_marker(label)
        if position is None or position >= len(songs):
            songs.append(item)
            self.touch_setlist()
            return len(songs) - 1
        if position < 0:
            position = 0
        songs.insert(position, item)
        self.touch_setlist()
        return position

    def update_marker_label(self, idx: int, label: str) -> bool:
        """Opdater label på en markør. Returnerer True hvis OK."""
        songs = self.current_setlist["songs"]
        if not (0 <= idx < len(songs)):
            return False
        if not is_marker_item(songs[idx]):
            return False
        label = (label or "").strip()
        if not label:
            return False
        songs[idx] = make_marker(label)
        self.touch_setlist()
        return True

    def remove_from_setlist_by_index(self, idx: int) -> None:
        songs = self.current_setlist["songs"]
        if 0 <= idx < len(songs):
            songs.pop(idx)
            self.touch_setlist()

    def move_up(self, idx: int) -> int:
        songs = self.current_setlist["songs"]
        if 1 <= idx < len(songs):
            songs[idx - 1], songs[idx] = songs[idx], songs[idx - 1]
            self.touch_setlist()
            return idx - 1
        return idx

    def move_down(self, idx: int) -> int:
        songs = self.current_setlist["songs"]
        if 0 <= idx < len(songs) - 1:
            songs[idx + 1], songs[idx] = songs[idx], songs[idx + 1]
            self.touch_setlist()
            return idx + 1
        return idx

    def move_to(self, src_idx: int, dst_idx: int) -> int:
        songs = self.current_setlist["songs"]
        if not (0 <= src_idx < len(songs)) or not (0 <= dst_idx < len(songs)):
            return src_idx
        item = songs.pop(src_idx)
        songs.insert(dst_idx, item)
        if src_idx != dst_idx:
            self.touch_setlist()
        return dst_idx

    def clear_current_setlist(self) -> None:
        self.current_setlist["songs"] = []
        self.touch_setlist()

    def current_setlist_seconds(self) -> int:
        total = 0
        for item in self.current_setlist["songs"]:
            name = item_song_name(item)
            if not name:
                continue
            s = self.get_song(name)
            if s:
                total += parse_duration(s["duration"])
        return total

    def current_setlist_song_count(self) -> int:
        """Antallet af RIGTIGE sange (ekskl. markører) i den aktive setliste."""
        return sum(1 for it in self.current_setlist["songs"] if item_song_name(it))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search_songs(self, query: str, all_bands: bool = False) -> List[Tuple[int, int, Dict]]:
        """Find sange der matcher `query`.

        Returnerer en liste af (band_idx, song_idx_in_that_band, song_dict).
        all_bands=False søger kun i det aktive band.
        Tomt query returnerer alle sange i det valgte scope.
        """
        q = (query or "").strip().lower()
        if all_bands:
            scope = list(enumerate(self.bands))
        else:
            scope = [(self.active_band, self.current_band)]

        results: List[Tuple[int, int, Dict]] = []
        for bi, band in scope:
            for si, song in enumerate(band["library"]):
                if not q or self._song_matches(song, q):
                    results.append((bi, si, song))
        return results

    @staticmethod
    def _song_matches(song: Dict, q: str) -> bool:
        for field in ("name", "key", "notes"):
            value = (song.get(field) or "").lower()
            if q in value:
                return True
        return False

    def copy_song_to_current_band(self, band_idx: int, song_idx: int) -> bool:
        """Kopier en sang fra et andet bands bibliotek til det aktive bands.
        Returnerer False hvis sangen allerede findes i det aktive band."""
        if not (0 <= band_idx < len(self.bands)):
            return False
        src_lib = self.bands[band_idx]["library"]
        if not (0 <= song_idx < len(src_lib)):
            return False
        s = src_lib[song_idx]
        return self.add_song(
            s.get("name", ""),
            s.get("duration", ""),
            s.get("key", ""),
            s.get("notes", ""),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "bands": self.bands,
            "active_band": self.active_band,
            "print_options": self.print_options,
        }

    def from_dict(self, data: Dict) -> None:
        version = int(data.get("schema_version", 1))
        if version >= 3:
            raw_bands = data.get("bands", [])
            self.bands = [self._normalize_band(b) for b in raw_bands if isinstance(b, dict)]
            if not self.bands:
                self.bands = [new_band()]
            self.active_band = max(
                0, min(int(data.get("active_band", 0)), len(self.bands) - 1)
            )
            self.print_options = default_print_options()
            opts = data.get("print_options", {})
            if isinstance(opts, dict):
                for k, default in default_print_options().items():
                    if k in opts:
                        if isinstance(default, bool):
                            self.print_options[k] = bool(opts[k])
                        else:
                            value = opts[k]
                            if k == "font_size" and value in ("small", "medium", "large"):
                                self.print_options[k] = value
                            elif isinstance(default, str):
                                self.print_options[k] = str(value)
        elif version == 2:
            band = self._normalize_band(
                {
                    "name": "Mit band",
                    "library": data.get("library", []),
                    "setlists": data.get("setlists", []),
                    "active_setlist": data.get("active_setlist", 0),
                }
            )
            self.bands = [band]
            self.active_band = 0
            self.print_options = default_print_options()
        else:
            # v1
            library = [self._normalize_song(s) for s in data.get("library", [])]
            old = data.get("setlist", [])
            band = new_band("Mit band")
            band["library"] = library
            band["setlists"] = [
                {
                    "name": "Importeret setliste",
                    "songs": [s for s in old if isinstance(s, str)],
                }
            ]
            band["active_setlist"] = 0
            self.bands = [band]
            self.active_band = 0
            self.print_options = default_print_options()

    @classmethod
    def _normalize_band(cls, b: Dict) -> Dict:
        library = [cls._normalize_song(s) for s in b.get("library", [])]
        raw_setlists = b.get("setlists", [])
        setlists = []
        for sl in raw_setlists:
            if not isinstance(sl, dict):
                continue
            # modified_at fra gamle filer: hvis det mangler, sæt tom string
            # (vises som "ukendt" i UI) — vi gætter ikke en falsk dato.
            modified = sl.get("modified_at", "")
            if not isinstance(modified, str):
                modified = ""
            setlists.append(
                {
                    "name": str(sl.get("name", "Setliste")).strip() or "Setliste",
                    "songs": cls._normalize_setlist_items(sl.get("songs", [])),
                    "modified_at": modified,
                }
            )
        if not setlists:
            setlists = [new_setlist()]
        active = max(0, min(int(b.get("active_setlist", 0)), len(setlists) - 1))
        logo = b.get("logo_base64", "")
        if not isinstance(logo, str):
            logo = ""
        return {
            "name": str(b.get("name", "Mit band")).strip() or "Mit band",
            "library": library,
            "setlists": setlists,
            "active_setlist": active,
            "logo_base64": logo,
        }

    @staticmethod
    def _normalize_setlist_items(items) -> List:
        """Filtrer setlist-items: kun strings (sangnavne) og dict'er med 'marker' key."""
        out: List = []
        if not isinstance(items, list):
            return out
        for it in items:
            if isinstance(it, str) and it.strip():
                out.append(it)
            elif isinstance(it, dict) and "marker" in it:
                label = str(it.get("marker", "")).strip()
                if label:
                    out.append({"marker": label})
        return out

    @staticmethod
    def _normalize_song(s) -> Dict:
        if isinstance(s, str):
            return new_song(s)
        if isinstance(s, dict):
            return new_song(
                s.get("name", ""),
                s.get("duration", ""),
                s.get("key", ""),
                s.get("notes", ""),
            )
        return new_song(str(s))

    def save_to_path(self, path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load_from_path(self, path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.from_dict(data)

    def autosave(self) -> bool:
        try:
            self.save_to_path(default_autosave_path())
            return True
        except OSError:
            return False

    def load_autosave_if_exists(self) -> bool:
        path = default_autosave_path()
        if path.exists():
            try:
                self.load_from_path(path)
                return True
            except (OSError, json.JSONDecodeError, ValueError):
                return False
        return False

    # ------------------------------------------------------------------
    # Band logo
    # ------------------------------------------------------------------
    def set_band_logo(self, data_url: str) -> None:
        """Sæt aktivt bands logo. Forventer en data-URL ('data:image/...;base64,...')."""
        self.current_band["logo_base64"] = data_url or ""

    def clear_band_logo(self) -> None:
        self.current_band["logo_base64"] = ""

    def get_band_logo(self) -> str:
        return self.current_band.get("logo_base64", "") or ""

    # ------------------------------------------------------------------
    # A4 HTML export
    # ------------------------------------------------------------------
    def generate_html(self, title: str = "", options: Optional[Dict] = None) -> str:
        # Flet de givne options med modellens defaults
        opts = dict(self.print_options)
        valid_sizes = set(FONT_SIZES_PT.keys())
        if options:
            for k, v in options.items():
                if k not in opts:
                    continue
                default = default_print_options()[k]
                if isinstance(default, bool):
                    opts[k] = bool(v)
                elif k == "font_size" and v in valid_sizes:
                    opts[k] = v
                elif isinstance(default, str):
                    opts[k] = str(v)

        # Tekststørrelser
        sizes = FONT_SIZES_PT.get(opts.get("font_size", "medium"), FONT_SIZES_PT["medium"])

        sl = self.current_setlist
        band_name = self.current_band["name"]
        logo = self.get_band_logo() if opts.get("show_logo", True) else ""
        safe_title = (title or sl["name"] or f"Setliste {datetime.now().date()}").strip()

        # ---- Kolonner ----
        col_specs: List[Tuple[str, str, str]] = []  # (id, label, width)
        if opts["show_number"]:
            col_specs.append(("num", "#", "6%"))
        col_specs.append(("song", "Sang", "auto"))
        if opts["show_key"]:
            col_specs.append(("key", "Toneart", "12%"))
        if opts["show_duration"]:
            col_specs.append(("dur", "Længde", "12%"))
        if opts["show_notes"]:
            col_specs.append(("notes", "Noter", "32%"))

        used_pct = sum(
            int(w.replace("%", "")) for _, _, w in col_specs if w != "auto"
        )
        song_width = f"{max(100 - used_pct, 30)}%"
        ncols = len(col_specs)

        # Table header
        thead_html = ""
        if opts.get("show_table_header", True):
            th_html = "".join(
                "<th class='c-{cid}' style='width:{w}'>{label}</th>".format(
                    cid=cid,
                    w=(song_width if cid == "song" else w),
                    label=_html_escape(label),
                )
                for cid, label, w in col_specs
            )
            thead_html = f"<thead><tr>{th_html}</tr></thead>"

        # ---- Rækker (sange + markører) ----
        rows_html: List[str] = []
        total_seconds = 0
        song_num = 0
        show_markers = opts.get("show_markers", True)

        for item in sl["songs"]:
            if is_marker_item(item):
                if not show_markers:
                    continue
                label = item_marker_label(item)
                rows_html.append(
                    f"<tr class='marker-row'>"
                    f"<td class='marker' colspan='{ncols}'>{_html_escape(label)}</td>"
                    f"</tr>"
                )
                continue

            # Almindelig sang
            name = item_song_name(item)
            if not name:
                continue
            song_num += 1
            song = self.get_song(name) or new_song(name)
            total_seconds += parse_duration(song["duration"])
            cells = []
            for cid, _, _ in col_specs:
                if cid == "num":
                    cells.append(f"<td class='c-num'>{song_num}</td>")
                elif cid == "song":
                    cells.append(f"<td class='c-song'>{_html_escape(song['name'])}</td>")
                elif cid == "key":
                    cells.append(f"<td class='c-key'>{_html_escape(song['key'])}</td>")
                elif cid == "dur":
                    cells.append(f"<td class='c-dur'>{_html_escape(song['duration'])}</td>")
                elif cid == "notes":
                    cells.append(f"<td class='c-notes'>{_html_escape(song['notes'])}</td>")
            rows_html.append("<tr>" + "".join(cells) + "</tr>")

        # ---- Footer ----
        total_line = ""
        if opts.get("show_total_time", True) and total_seconds > 0:
            total_line = (
                f"<p class='total'>Samlet spilletid: "
                f"<strong>{format_seconds(total_seconds)}</strong></p>"
            )

        # ---- Header (titel + meta + logo) ----
        title_html = ""
        if opts.get("show_title", True):
            title_html = f"<h1>{_html_escape(safe_title)}</h1>"

        meta_html = ""
        if opts.get("show_meta", True):
            meta_bits = []
            if band_name:
                meta_bits.append(_html_escape(band_name))
            if opts.get("show_date", True):
                meta_bits.append(
                    f"Genereret {datetime.now().strftime('%d-%m-%Y %H:%M')}"
                )
            meta_bits.append(f"{song_num} sange")
            meta_html = f"<p class='meta'>{' · '.join(meta_bits)}</p>"

        logo_html = ""
        if logo:
            logo_html = (
                f"<div class='header-right'>"
                f"<img src='{_html_escape(logo)}' alt='Logo' /></div>"
            )

        header_html = ""
        if title_html or meta_html or logo_html:
            header_html = (
                f"<div class='header'>"
                f"<div class='header-left'>{title_html}{meta_html}</div>"
                f"{logo_html}"
                f"</div>"
            )

        css = f"""
        @page {{ size: A4; margin: 18mm; }}
        * {{ box-sizing: border-box; }}
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; color: #111; }}
        .header {{ display: flex; justify-content: space-between;
                  align-items: flex-start; gap: 16pt; margin-bottom: 12pt; }}
        .header-left {{ flex: 1; min-width: 0; }}
        .header-right img {{ max-height: 80pt; max-width: 180pt;
                            object-fit: contain; display: block; }}
        h1 {{ font-size: {sizes['title']}pt; margin: 0 0 4pt 0; line-height: 1.1; }}
        .meta {{ color: #555; font-size: {sizes['meta']}pt; margin: 0; }}
        table {{ width: 100%; border-collapse: collapse;
                font-size: {sizes['table']}pt; }}
        th, td {{ padding: 6pt 8pt; border-bottom: 1px solid #ccc;
                 text-align: left; vertical-align: top; }}
        th {{ background: #f0f0f0; font-size: {max(sizes['table'] - 3, 9)}pt;
             text-transform: uppercase; letter-spacing: 0.5pt; }}
        .c-num {{ color: #888; }}
        .c-song {{ font-weight: bold; }}
        .c-notes {{ color: #333; font-size: {sizes['notes']}pt; }}
        .total {{ margin-top: 14pt; font-size: {sizes['total']}pt; color: #333; }}
        .marker-row td.marker {{
            background: #fff7d6;
            color: #6b4f00;
            font-weight: bold;
            font-style: italic;
            text-transform: uppercase;
            letter-spacing: 1pt;
            text-align: center;
            border-top: 2px solid #d4b300;
            border-bottom: 2px solid #d4b300;
            padding: 8pt;
        }}
        """

        return (
            "<!doctype html><html lang='da'><head><meta charset='utf-8'>"
            f"<title>{_html_escape(safe_title)}</title>"
            f"<style>{css}</style></head><body>"
            f"{header_html}"
            f"<table>{thead_html}"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
            f"{total_line}</body></html>"
        )


def _html_escape(s) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
