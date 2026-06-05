"""Headless tests for the SetlistModel — schema v3 + backwards compat."""

import json
import tempfile
from pathlib import Path

from setlist_model import (
    SCHEMA_VERSION,
    SetlistModel,
    default_print_options,
    format_seconds,
    new_song,
    parse_duration,
)


def _tmp_json() -> Path:
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    p = Path(tf.name)
    tf.close()
    return p


# ===========================================================================
# Basic save/load (v2-style API still works via property proxies)
# ===========================================================================
def test_basic_save_load_roundtrip() -> None:
    m = SetlistModel()
    m.add_song("Wonderwall", duration="4:30", key="F#m", notes="Capo 2")
    m.add_song("Hey Jude", duration="7:11", key="F")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)

    p = _tmp_json()
    m.save_to_path(p)

    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.library == m.library
    assert m2.setlists == m.setlists
    assert m2.active_setlist == m.active_setlist
    print("  basic roundtrip OK")


def test_song_fields_preserved() -> None:
    m = SetlistModel()
    m.add_song("Test", duration="3:21", key="Am", notes="Line 1\nLine 2")
    p = _tmp_json()
    m.save_to_path(p)
    m2 = SetlistModel()
    m2.load_from_path(p)
    s = m2.get_song("Test")
    assert s and s["duration"] == "3:21" and s["key"] == "Am"
    assert s["notes"] == "Line 1\nLine 2"
    print("  song fields OK")


# ===========================================================================
# Setlists (within one band)
# ===========================================================================
def test_multiple_setlists() -> None:
    m = SetlistModel()
    for n in ("A", "B", "C"):
        m.add_song(n)
    m.rename_setlist(0, "Sæt 1")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)
    m.add_setlist("Sæt 2")
    m.add_to_setlist_by_index(2)
    m.add_to_setlist_by_index(0)

    assert len(m.setlists) == 2
    assert m.setlists[0]["songs"] == ["A", "B"]
    assert m.setlists[1]["songs"] == ["C", "A"]
    assert m.active_setlist == 1

    p = _tmp_json()
    m.save_to_path(p)
    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.setlists == m.setlists
    print("  multiple setlists OK")


def test_cannot_delete_last_setlist() -> None:
    m = SetlistModel()
    assert m.delete_setlist(0) is False
    print("  last-setlist protection OK")


# ===========================================================================
# NEW: Bands
# ===========================================================================
def test_multiple_bands() -> None:
    m = SetlistModel()
    m.rename_band(0, "Band A")
    m.add_song("Song 1")
    m.add_band("Band B")
    assert m.active_band == 1
    assert m.library == []  # New band starts empty
    m.add_song("Song 2")

    assert m.band_names() == ["Band A", "Band B"]
    assert m.bands[0]["library"][0]["name"] == "Song 1"
    assert m.bands[1]["library"][0]["name"] == "Song 2"

    # Switch back
    m.set_active_band(0)
    assert m.song_names() == ["Song 1"]

    p = _tmp_json()
    m.save_to_path(p)
    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.band_names() == ["Band A", "Band B"]
    assert m2.active_band == 0
    assert m2.song_names() == ["Song 1"]
    print("  multiple bands OK")


def test_cannot_delete_last_band() -> None:
    m = SetlistModel()
    assert m.delete_band(0) is False
    print("  last-band protection OK")


def test_delete_band_adjusts_active() -> None:
    m = SetlistModel()
    m.rename_band(0, "A")
    m.add_band("B")
    m.add_band("C")  # active_band = 2
    assert m.delete_band(1) is True  # remove B
    assert m.band_names() == ["A", "C"]
    # active_band should still point to a valid band
    assert 0 <= m.active_band < 2
    print("  delete band adjusts active OK")


def test_rename_band() -> None:
    m = SetlistModel()
    assert m.rename_band(0, "Mit fede band") is True
    assert m.band_names()[0] == "Mit fede band"
    assert m.rename_band(0, "  ") is False  # blank rejected
    print("  rename band OK")


# ===========================================================================
# NEW: Search
# ===========================================================================
def test_search_in_current_band_only() -> None:
    m = SetlistModel()
    m.add_song("Wonderwall")
    m.add_song("Hey Jude")
    m.add_song("Smoke on the Water", notes="Deep Purple classic")

    # Name match
    res = m.search_songs("wonder")
    assert len(res) == 1 and res[0][2]["name"] == "Wonderwall"

    # Notes match
    res = m.search_songs("deep purple")
    assert len(res) == 1 and res[0][2]["name"] == "Smoke on the Water"

    # Empty query returns all
    assert len(m.search_songs("")) == 3
    print("  search current band OK")


def test_search_all_bands() -> None:
    m = SetlistModel()
    m.rename_band(0, "Band A")
    m.add_song("Wonderwall")
    m.add_band("Band B")
    m.add_song("Hey Jude")
    m.add_song("Wonder Years")

    # Current band only — should find 1
    res = m.search_songs("wonder", all_bands=False)
    assert len(res) == 1
    assert res[0][0] == 1  # band B

    # All bands — should find 2
    res = m.search_songs("wonder", all_bands=True)
    assert len(res) == 2
    band_indices = {r[0] for r in res}
    assert band_indices == {0, 1}
    print("  search all bands OK")


def test_copy_song_to_current_band() -> None:
    m = SetlistModel()
    m.add_song("Wonderwall", key="F#m", duration="4:30")
    m.add_band("Band B")
    # In Band B, copy Wonderwall from Band A
    assert m.copy_song_to_current_band(0, 0) is True
    s = m.get_song("Wonderwall")
    assert s and s["key"] == "F#m" and s["duration"] == "4:30"
    # Second copy fails (duplicate)
    assert m.copy_song_to_current_band(0, 0) is False
    print("  copy song between bands OK")


# ===========================================================================
# NEW: Print options
# ===========================================================================
def test_print_options_default() -> None:
    opts = default_print_options()
    expected_bool_keys = {
        # Header
        "show_title",
        "show_meta",
        "show_date",
        "show_logo",
        # Tabel
        "show_table_header",
        "show_number",
        "show_key",
        "show_duration",
        "show_notes",
        # Footer + sektioner
        "show_total_time",
        "show_markers",
    }
    # Alle bool-keys default til True
    for k in expected_bool_keys:
        assert opts.get(k) is True, f"{k} skal default til True"
    # Plus font_size (string)
    assert opts.get("font_size") in ("xsmall", "small", "medium", "large", "xlarge")
    # Ingen ukendte keys
    assert set(opts.keys()) == expected_bool_keys | {"font_size"}
    print("  print options defaults OK")


def test_print_options_persisted() -> None:
    m = SetlistModel()
    m.print_options["show_notes"] = False
    m.print_options["show_total_time"] = False
    p = _tmp_json()
    m.save_to_path(p)
    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.print_options["show_notes"] is False
    assert m2.print_options["show_total_time"] is False
    assert m2.print_options["show_number"] is True
    print("  print options persisted OK")


def test_html_export_all_columns() -> None:
    m = SetlistModel()
    m.add_song("Hey Jude", duration="7:11", key="F", notes="Long outro")
    m.add_to_setlist_by_index(0)
    html = m.generate_html("Koncert")
    assert "Koncert" in html
    assert "Hey Jude" in html
    assert "7:11" in html
    assert ">F<" in html
    assert "Long outro" in html
    assert "Samlet spilletid" in html
    print("  HTML all columns OK")


def test_html_export_minimal_columns() -> None:
    m = SetlistModel()
    m.add_song("Hey Jude", duration="7:11", key="F", notes="Long outro")
    m.add_to_setlist_by_index(0)
    html = m.generate_html(
        "Minimal",
        {
            "show_number": False,
            "show_key": False,
            "show_duration": False,
            "show_notes": False,
            "show_total_time": False,
        },
    )
    # Song name MUST still be there
    assert "Hey Jude" in html
    # Optional bits MUST be gone
    assert "7:11" not in html
    assert "Long outro" not in html
    assert "Samlet spilletid" not in html
    assert "Toneart" not in html
    print("  HTML minimal columns OK")


def test_html_includes_band_name() -> None:
    m = SetlistModel()
    m.rename_band(0, "Mit fede band")
    m.add_song("Song 1", duration="3:00")
    m.add_to_setlist_by_index(0)
    html = m.generate_html("Test")
    assert "Mit fede band" in html
    print("  HTML includes band name OK")


# ===========================================================================
# Migrations from older schemas
# ===========================================================================
def test_v1_migration() -> None:
    p = _tmp_json()
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"library": ["A", "B", "C"], "setlist": ["B", "C"]}, f)
    m = SetlistModel()
    m.load_from_path(p)
    assert m.band_names() == ["Mit band"]
    assert [s["name"] for s in m.library] == ["A", "B", "C"]
    assert m.setlists[0]["songs"] == ["B", "C"]

    # Re-saving upgrades schema
    m.save_to_path(p)
    with open(p) as f:
        raw = json.load(f)
    assert raw["schema_version"] == SCHEMA_VERSION
    assert "bands" in raw
    print("  v1 → v3 migration OK")


def test_v2_migration() -> None:
    p = _tmp_json()
    data = {
        "schema_version": 2,
        "library": [
            {"name": "Wonderwall", "key": "F#m", "duration": "4:30", "notes": ""},
            {"name": "Hey Jude", "key": "F", "duration": "7:11", "notes": "Outro"},
        ],
        "setlists": [
            {"name": "Sæt 1", "songs": ["Wonderwall"]},
            {"name": "Sæt 2", "songs": ["Hey Jude", "Wonderwall"]},
        ],
        "active_setlist": 1,
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    m = SetlistModel()
    m.load_from_path(p)
    assert m.band_names() == ["Mit band"]
    assert [s["name"] for s in m.library] == ["Wonderwall", "Hey Jude"]
    assert len(m.setlists) == 2
    assert m.setlists[1]["songs"] == ["Hey Jude", "Wonderwall"]
    assert m.active_setlist == 1
    print("  v2 → v3 migration OK")


# ===========================================================================
# Other existing behavior
# ===========================================================================
def test_rename_song_updates_setlists_in_current_band() -> None:
    m = SetlistModel()
    m.add_song("Old")
    m.add_to_setlist_by_index(0)
    m.add_setlist("Sæt 2")
    m.add_to_setlist_by_index(0)

    assert m.update_song("Old", "New", "", "G", "")
    assert m.setlists[0]["songs"] == ["New"]
    assert m.setlists[1]["songs"] == ["New"]
    print("  rename propagates OK")


def test_delete_song_removes_from_band_setlists() -> None:
    m = SetlistModel()
    m.add_song("A")
    m.add_song("B")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)
    m.remove_song_by_index(0)
    assert m.song_names() == ["B"]
    assert m.setlists[0]["songs"] == ["B"]
    print("  delete propagates OK")


def test_move_operations() -> None:
    m = SetlistModel()
    for n in ("A", "B", "C", "D"):
        m.add_song(n)
        m.add_to_setlist_by_index(m.song_names().index(n))
    assert m.move_up(2) == 1
    assert m.current_setlist["songs"] == ["A", "C", "B", "D"]
    assert m.move_down(0) == 1
    assert m.current_setlist["songs"] == ["C", "A", "B", "D"]
    assert m.move_to(0, 3) == 3
    assert m.current_setlist["songs"] == ["A", "B", "D", "C"]
    print("  move operations OK")


def test_duration_helpers() -> None:
    assert parse_duration("4:30") == 270
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("90") == 90
    assert parse_duration("") == 0
    assert parse_duration("bad") == 0
    assert format_seconds(270) == "4:30"
    assert format_seconds(3723) == "1:02:03"
    assert format_seconds(0) == "0:00"
    print("  duration helpers OK")


def test_new_song_factory_strips_whitespace() -> None:
    s = new_song("  Hey  ", duration="  3:00 ", key="  G ", notes=" hi ")
    assert s == {"name": "Hey", "duration": "3:00", "key": "G", "notes": "hi"}
    print("  factory whitespace OK")


def test_each_band_has_independent_setlists() -> None:
    m = SetlistModel()
    m.add_song("X")
    m.add_to_setlist_by_index(0)
    m.add_band("B2")
    # New band shouldn't have access to X
    assert m.song_names() == []
    assert m.current_setlist["songs"] == []
    # Switch back
    m.set_active_band(0)
    assert m.song_names() == ["X"]
    assert m.current_setlist["songs"] == ["X"]
    print("  band isolation OK")


# ===========================================================================
# music_search — offline tests (kører altid)
# ===========================================================================
def test_music_search_format_duration() -> None:
    from music_search import format_duration
    assert format_duration(None) == ""
    assert format_duration(0) == ""
    assert format_duration(-1) == ""
    assert format_duration(45) == "0:45"
    assert format_duration(125) == "2:05"
    assert format_duration(3725) == "1:02:05"
    print("  music_search format_duration OK")


def test_music_search_format_artist_label() -> None:
    from music_search import format_artist_label
    assert "D-A-D" in format_artist_label(
        {"name": "D-A-D", "country": "DK", "type": "Group", "disambiguation": "Danish rock"}
    )
    bare = format_artist_label({"name": "X"})
    assert bare == "X"
    print("  music_search format_artist_label OK")


def test_music_search_make_recording() -> None:
    from music_search import _make_recording
    r1 = _make_recording("Song", 270)
    assert r1["title"] == "Song"
    assert r1["duration_seconds"] == 270
    assert r1["duration"] == "4:30"
    r2 = _make_recording("Other", None)
    assert r2["duration"] == ""
    print("  music_search _make_recording OK")


def test_music_search_is_live_version() -> None:
    from music_search import is_live_version
    # Skal genkende som live
    live_titles = [
        "Wonderwall (Live)",
        "Wonderwall (Live at Wembley)",
        "Wonderwall (Live in Tokyo, 2019)",
        "Wonderwall (Live, 1996)",
        "Wonderwall [Live]",
        "Wonderwall - Live",
        "Wonderwall \u2013 Live at Earls Court",  # en-dash
        "Wonderwall \u2014 Live",                  # em-dash
        "Wonderwall (Live Version)",
        "Wonderwall (Live recording)",
        "Wonderwall (LIVE)",
        "Wonderwall (live acoustic)",
    ]
    for t in live_titles:
        assert is_live_version(t), f"Burde være live: {t!r}"

    # MÅ IKKE genkendes som live (false positives)
    not_live_titles = [
        "Wonderwall",
        "Live and Let Die",
        "Live at the BBC",
        "Aliveness",
        "Olive Garden",
        "A Drug for the Heart",
        "Hey Jude (Acoustic)",
        "Wonderwall (Remastered 2014)",
        "",
        None,
    ]
    for t in not_live_titles:
        assert not is_live_version(t), f"Må IKKE være live: {t!r}"
    print("  music_search is_live_version OK")


def test_music_search_filter_out_live() -> None:
    from music_search import filter_out_live
    recs = [
        {"title": "Wonderwall", "duration": "4:30", "duration_seconds": 270},
        {"title": "Wonderwall (Live)", "duration": "5:10", "duration_seconds": 310},
        {"title": "Hey Jude", "duration": "7:11", "duration_seconds": 431},
        {"title": "Hey Jude - Live", "duration": "8:00", "duration_seconds": 480},
        {"title": "Live and Let Die", "duration": "3:11", "duration_seconds": 191},
    ]
    filtered = filter_out_live(recs)
    titles = [r["title"] for r in filtered]
    assert titles == ["Wonderwall", "Hey Jude", "Live and Let Die"]
    # Original list er urørt
    assert len(recs) == 5
    print("  music_search filter_out_live OK")


# ===========================================================================
# Logo + tekststørrelse (Fase 11)
# ===========================================================================
def test_band_logo_set_clear_get() -> None:
    m = SetlistModel()
    assert m.get_band_logo() == ""
    fake = "data:image/png;base64,ABC123="
    m.set_band_logo(fake)
    assert m.get_band_logo() == fake
    m.clear_band_logo()
    assert m.get_band_logo() == ""
    print("  band logo set/clear/get OK")


def test_band_logo_persisted_per_band() -> None:
    m = SetlistModel()
    m.set_band_logo("data:image/png;base64,AAA=")
    m.add_band("Band 2")  # add_band switcher til det nye band
    assert m.get_band_logo() == ""
    m.set_band_logo("data:image/png;base64,BBB=")
    # Skift tilbage til band 0
    m.set_active_band(0)
    assert m.get_band_logo() == "data:image/png;base64,AAA="
    m.set_active_band(1)
    assert m.get_band_logo() == "data:image/png;base64,BBB="
    print("  band logo persisted per band OK")


def test_band_logo_saved_to_disk() -> None:
    m = SetlistModel()
    fake = "data:image/png;base64,SAVEME="
    m.set_band_logo(fake)
    p = _tmp_json()
    m.save_to_path(p)

    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.get_band_logo() == fake
    print("  band logo persisted to disk OK")


def test_print_options_includes_font_size_and_logo() -> None:
    opts = default_print_options()
    assert "font_size" in opts
    assert opts["font_size"] in ("xsmall", "small", "medium", "large", "xlarge")
    assert "show_logo" in opts
    assert isinstance(opts["show_logo"], bool)
    print("  default_print_options has font_size + show_logo OK")


def test_font_size_persisted() -> None:
    m = SetlistModel()
    m.print_options = {**default_print_options(), "font_size": "large"}
    p = _tmp_json()
    m.save_to_path(p)

    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.print_options["font_size"] == "large"
    print("  font_size persisted OK")


def test_html_contains_logo_when_set_and_show_logo_true() -> None:
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    fake = "data:image/png;base64,TESTLOGO=="
    m.set_band_logo(fake)
    html = m.generate_html("My Show", {**default_print_options(), "show_logo": True})
    assert fake in html, "Logo data-URL skal være i HTML"
    assert "header-right" in html, "Header-right div skal eksistere"
    print("  HTML contains logo when show_logo=True OK")


def test_html_omits_logo_when_show_logo_false() -> None:
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    fake = "data:image/png;base64,HIDDEN=="
    m.set_band_logo(fake)
    html = m.generate_html("My Show", {**default_print_options(), "show_logo": False})
    assert fake not in html, "Logo skal IKKE være i HTML når show_logo=False"
    print("  HTML omits logo when show_logo=False OK")


def test_html_omits_logo_when_band_has_no_logo() -> None:
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    # Intet logo sat
    html = m.generate_html("My Show", {**default_print_options(), "show_logo": True})
    assert "data:image/png;base64" not in html
    print("  HTML omits logo when band has no logo OK")


def test_html_font_size_changes_title_size() -> None:
    from setlist_model import FONT_SIZES_PT
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    html_small = m.generate_html("X", {**default_print_options(), "font_size": "small"})
    html_large = m.generate_html("X", {**default_print_options(), "font_size": "large"})
    small_title = f"{FONT_SIZES_PT['small']['title']}pt"
    large_title = f"{FONT_SIZES_PT['large']['title']}pt"
    assert small_title in html_small
    assert large_title in html_large
    assert small_title != large_title  # sanity
    print("  HTML font_size changes title size OK")


# ===========================================================================
# Greying + dup-beskyttelse + udvidede tekststørrelser (Fase 12)
# ===========================================================================
def test_is_in_current_setlist() -> None:
    m = SetlistModel()
    m.add_song("Wonderwall")
    m.add_song("Hey Jude")
    assert m.is_in_current_setlist("Wonderwall") is False
    m.add_to_setlist_by_index(0)
    assert m.is_in_current_setlist("Wonderwall") is True
    assert m.is_in_current_setlist("Hey Jude") is False
    assert m.is_in_current_setlist("") is False
    assert m.is_in_current_setlist("Findes Ikke") is False
    print("  is_in_current_setlist OK")


def test_add_to_setlist_returns_bool_and_blocks_duplicates() -> None:
    m = SetlistModel()
    m.add_song("Wonderwall")
    m.add_song("Hey Jude")
    # Første tilføjelse lykkes
    assert m.add_to_setlist_by_index(0) is True
    # Anden tilføjelse af samme sang fejler
    assert m.add_to_setlist_by_index(0) is False
    # Anden sang lykkes
    assert m.add_to_setlist_by_index(1) is True
    # Ugyldigt index fejler
    assert m.add_to_setlist_by_index(99) is False
    assert m.add_to_setlist_by_index(-1) is False
    # Setlisten har præcis 2 sange — ingen duplikater
    assert m.current_setlist["songs"] == ["Wonderwall", "Hey Jude"]
    print("  add_to_setlist returns bool + blocks duplicates OK")


def test_font_sizes_pt_has_five_levels() -> None:
    from setlist_model import FONT_SIZES_PT
    expected = {"xsmall", "small", "medium", "large", "xlarge"}
    assert set(FONT_SIZES_PT.keys()) == expected
    # Hver size har de samme keys
    keys = {"title", "meta", "table", "notes", "total"}
    for name, sizes in FONT_SIZES_PT.items():
        assert set(sizes.keys()) == keys, f"{name} mangler keys"
    # Størrelser stiger monotont fra xsmall til xlarge
    order = ["xsmall", "small", "medium", "large", "xlarge"]
    titles = [FONT_SIZES_PT[k]["title"] for k in order]
    assert titles == sorted(titles), f"title-sizes skal være stigende: {titles}"
    assert titles[0] < titles[-1]
    print("  FONT_SIZES_PT has 5 levels (monotonic) OK")


def test_html_uses_xsmall_and_xlarge_correctly() -> None:
    from setlist_model import FONT_SIZES_PT
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    for size in ("xsmall", "xlarge"):
        html = m.generate_html("X", {**default_print_options(), "font_size": size})
        expected_title = f"{FONT_SIZES_PT[size]['title']}pt"
        assert expected_title in html, f"{size} title-pt mangler i HTML"
    print("  HTML uses xsmall + xlarge OK")


def test_html_falls_back_for_unknown_font_size() -> None:
    # Ukendt size må ikke crashe — den falder tilbage til medium
    m = SetlistModel()
    m.add_song("Test", duration="3:00")
    m.add_to_setlist_by_index(0)
    html = m.generate_html("X", {**default_print_options(), "font_size": "gigantic"})
    # Skal indeholde medium-størrelse
    from setlist_model import FONT_SIZES_PT
    medium_title = f"{FONT_SIZES_PT['medium']['title']}pt"
    assert medium_title in html
    print("  HTML falls back to medium for unknown font_size OK")


# ===========================================================================
# Sektion-markører + alle vis/skjul-toggles (Fase 13)
# ===========================================================================
def test_marker_helpers() -> None:
    from setlist_model import is_marker_item, item_song_name, item_marker_label, make_marker
    assert is_marker_item({"marker": "Pause"}) is True
    assert is_marker_item("Wonderwall") is False
    assert is_marker_item({"name": "X"}) is False
    assert item_song_name("Wonderwall") == "Wonderwall"
    assert item_song_name({"marker": "Pause"}) == ""
    assert item_marker_label({"marker": "Pause"}) == "Pause"
    assert item_marker_label("Wonderwall") == ""
    assert make_marker("ekstra")["marker"] == "ekstra"
    assert make_marker("  ")["marker"] == "—"  # tom → placeholder
    print("  marker helpers OK")


def test_add_marker_to_setlist() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_song("B")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)
    # Markør til sidst
    i = m.add_marker_to_setlist("EKSTRA-NUMMER")
    assert i == 2
    assert m.current_setlist["songs"][2] == {"marker": "EKSTRA-NUMMER"}
    # Markør på position 1
    i = m.add_marker_to_setlist("PAUSE", position=1)
    assert i == 1
    assert m.current_setlist["songs"][1] == {"marker": "PAUSE"}
    # Tom label → fejl
    assert m.add_marker_to_setlist("   ") == -1
    print("  add_marker_to_setlist OK")


def test_update_marker_label() -> None:
    m = SetlistModel()
    m.add_marker_to_setlist("Test")
    assert m.update_marker_label(0, "Opdateret") is True
    assert m.current_setlist["songs"][0] == {"marker": "Opdateret"}
    # Tom label fejler
    assert m.update_marker_label(0, "  ") is False
    # Ugyldigt index fejler
    assert m.update_marker_label(99, "X") is False
    print("  update_marker_label OK")


def test_marker_not_counted_as_song() -> None:
    m = SetlistModel()
    m.add_song("A", duration="3:00")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("EKSTRA-NUMMER")
    assert m.current_setlist_song_count() == 1
    assert m.is_in_current_setlist("A") is True
    assert m.is_in_current_setlist("EKSTRA-NUMMER") is False
    # Markører bidrager IKKE til samlet tid
    assert m.current_setlist_seconds() == 180
    print("  marker not counted as song OK")


def test_marker_survives_rename_and_delete() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_song("B")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("PAUSE")
    m.add_to_setlist_by_index(1)
    # Omdøb A
    m.update_song("A", "A2", "", "", "")
    items = m.current_setlist["songs"]
    assert items == ["A2", {"marker": "PAUSE"}, "B"]
    # Slet A2
    a_idx = next(i for i, s in enumerate(m.library) if s["name"] == "A2")
    m.remove_song_by_index(a_idx)
    items = m.current_setlist["songs"]
    assert items == [{"marker": "PAUSE"}, "B"]
    print("  marker survives rename + delete OK")


def test_marker_persists_to_disk() -> None:
    m = SetlistModel()
    m.add_song("A")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("EKSTRA-NUMMER")
    p = _tmp_json()
    m.save_to_path(p)

    m2 = SetlistModel()
    m2.load_from_path(p)
    assert m2.current_setlist["songs"] == ["A", {"marker": "EKSTRA-NUMMER"}]
    print("  marker persists to disk OK")


def test_html_renders_markers_when_show_markers_true() -> None:
    m = SetlistModel()
    m.add_song("A", duration="3:00")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("EKSTRA-NUMMER")
    html = m.generate_html("T", {**default_print_options(), "show_markers": True})
    assert "EKSTRA-NUMMER" in html
    assert "marker-row" in html
    print("  HTML renders markers when show_markers=True OK")


def test_html_omits_markers_when_show_markers_false() -> None:
    m = SetlistModel()
    m.add_song("A", duration="3:00")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("EKSTRA-NUMMER")
    html = m.generate_html("T", {**default_print_options(), "show_markers": False})
    assert "EKSTRA-NUMMER" not in html
    print("  HTML omits markers when show_markers=False OK")


def test_html_show_title_toggle() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_to_setlist_by_index(0)
    html_on = m.generate_html("MIN TITEL", {**default_print_options(), "show_title": True})
    html_off = m.generate_html("MIN TITEL", {**default_print_options(), "show_title": False})
    assert "<h1>MIN TITEL</h1>" in html_on
    assert "<h1>" not in html_off
    print("  show_title toggle OK")


def test_html_show_meta_toggle() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_to_setlist_by_index(0)
    html_on = m.generate_html("T", {**default_print_options(), "show_meta": True})
    html_off = m.generate_html("T", {**default_print_options(), "show_meta": False})
    assert "<p class='meta'>" in html_on
    assert "<p class='meta'>" not in html_off
    print("  show_meta toggle OK")


def test_html_show_date_toggle() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_to_setlist_by_index(0)
    html_on = m.generate_html("T", {**default_print_options(), "show_date": True})
    html_off = m.generate_html("T", {**default_print_options(), "show_date": False})
    assert "Genereret" in html_on
    assert "Genereret" not in html_off
    # bandnavn skal stadig være der
    assert "Mit band" in html_off
    print("  show_date toggle OK")


def test_html_show_table_header_toggle() -> None:
    m = SetlistModel()
    m.add_song("A"); m.add_to_setlist_by_index(0)
    html_on = m.generate_html("T", {**default_print_options(), "show_table_header": True})
    html_off = m.generate_html("T", {**default_print_options(), "show_table_header": False})
    assert "<thead>" in html_on
    assert "<thead>" not in html_off
    print("  show_table_header toggle OK")


def test_all_print_options_persisted() -> None:
    """Sikrer at ALLE bool-toggles + markører kan slås fra og gemmes."""
    m = SetlistModel()
    opts = {k: False for k in default_print_options() if isinstance(default_print_options()[k], bool)}
    opts["font_size"] = "xlarge"
    m.print_options = opts
    p = _tmp_json()
    m.save_to_path(p)
    m2 = SetlistModel()
    m2.load_from_path(p)
    for k, v in opts.items():
        assert m2.print_options[k] == v, f"{k}: forventet {v}, fik {m2.print_options[k]}"
    print("  all print options persisted OK")


def test_old_setlist_format_still_works() -> None:
    """Bagudkompatibilitet: en v3-fil hvor songs kun er strings skal stadig virke."""
    import json
    p = _tmp_json()
    raw = {
        "schema_version": 3,
        "bands": [{
            "name": "Old Band",
            "library": [{"name": "Song A", "key": "", "duration": "3:00", "notes": ""}],
            "setlists": [{"name": "Old SL", "songs": ["Song A"]}],
            "active_setlist": 0,
        }],
        "active_band": 0,
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    m = SetlistModel()
    m.load_from_path(p)
    assert m.current_setlist["songs"] == ["Song A"]
    # Markører kan nu tilføjes til den gamle setliste
    m.add_marker_to_setlist("EKSTRA")
    assert m.current_setlist["songs"] == ["Song A", {"marker": "EKSTRA"}]
    print("  old setlist format (only strings) still works OK")


# ===========================================================================
# Regression-tests for bugs rapporteret af brugeren (juni 2026)
# ===========================================================================
def test_regression_markers_do_not_break_set_construction() -> None:
    """Bug: refresh_library_view kaldte set(songs) — crashede når der var
    markører (dicts er ikke hashable). Symptom: alle sange forsvandt fra
    biblioteket efter man trykkede 'Ekstra-nummer'.

    Fix: brug en set-comprehension der kun samler sang-navne og
    springer markører over.
    """
    from setlist_model import is_marker_item, item_song_name
    m = SetlistModel()
    m.add_song("Sang A")
    m.add_song("Sang B")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)
    m.add_marker_to_setlist("EKSTRA-NUMMER")

    # Det gamle (broken) udtryk ville crashe her:
    try:
        _ = set(m.current_setlist["songs"])
        old_broken = False
    except TypeError:
        old_broken = True
    assert old_broken, "Test-setup forkert — markøren burde være en dict"

    # Det nye (fixed) udtryk skal IKKE crashe:
    in_set = {item_song_name(it)
              for it in m.current_setlist["songs"]
              if not is_marker_item(it)}
    assert in_set == {"Sang A", "Sang B"}
    print("  regression: markers do not break set() construction OK")


def test_regression_can_add_song_after_marker() -> None:
    """Bug: efter man har tilføjet en markør, kunne man ikke tilføje
    flere sange (refresh_library_view crashede silent → biblioteket blev tomt).

    Vi simulerer her hele add-flowet uden GUI for at verificere at
    modellen kan håndtere det.
    """
    m = SetlistModel()
    m.add_song("Sang A")
    m.add_song("Sang B")
    m.add_song("Sang C")
    # Bruger tilføjer Sang A til setlisten
    assert m.add_to_setlist_by_index(0) is True
    # Bruger trykker "Ekstra-nummer"
    pos = m.add_marker_to_setlist("EKSTRA-NUMMER")
    assert pos == 1
    # Bruger tilføjer flere sange BAGEFTER (det er det der var broken)
    assert m.add_to_setlist_by_index(1) is True
    assert m.add_to_setlist_by_index(2) is True
    assert m.current_setlist["songs"] == [
        "Sang A",
        {"marker": "EKSTRA-NUMMER"},
        "Sang B",
        "Sang C",
    ]
    # Sang-tæller ignorerer markøren
    assert m.current_setlist_song_count() == 3
    print("  regression: can add songs after a marker OK")


def test_regression_notes_field_used_in_html_print() -> None:
    """Bug: brugeren skrev noter, men kunne ikke se dem i print-preview.
    HTML-printen havde dem dog hele tiden. Denne test sikrer at noterne
    rent faktisk renderes i HTML når show_notes=True.
    """
    m = SetlistModel()
    m.add_song("Wonderwall", key="Em", notes="Husk capo på 2. bånd")
    m.add_to_setlist_by_index(0)
    opts = default_print_options()
    opts["show_notes"] = True
    html = m.generate_html("Test", opts)
    assert "Husk capo på 2. bånd" in html, \
        "Noter skal være med i HTML når show_notes=True"
    # Modsat: når show_notes=False, må noterne IKKE være med
    opts["show_notes"] = False
    html2 = m.generate_html("Test", opts)
    assert "Husk capo på 2. bånd" not in html2, \
        "Noter må IKKE være med i HTML når show_notes=False"
    print("  regression: notes field renders in HTML print OK")


# ===========================================================================
# Updater (online opdaterings-tjek) — Fase 14
# Bruger mock-data så testene aldrig rør GitHub
# ===========================================================================
def test_updater_parse_version() -> None:
    from updater import parse_version
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version("1") == (1, 0, 0)
    assert parse_version("1.2.3-beta") == (1, 2, 3)
    assert parse_version("v2.0.0-rc1") == (2, 0, 0)
    assert parse_version("") == (0, 0, 0)
    assert parse_version("ingen-tal") == (0, 0, 0)
    assert parse_version(None) == (0, 0, 0)  # robust
    print("  updater parse_version OK")


def test_updater_is_newer() -> None:
    from updater import is_newer
    assert is_newer("1.2.0", "1.1.9") is True
    assert is_newer("v2.0.0", "1.9.9") is True
    assert is_newer("1.0.1", "1.0.0") is True
    assert is_newer("1.0.0", "1.0.0") is False
    assert is_newer("1.0.0", "1.0.1") is False
    assert is_newer("0.9.9", "1.0.0") is False
    # Robust mod prefix
    assert is_newer("v1.1.0", "v1.0.0") is True
    print("  updater is_newer OK")


def test_updater_parse_release_full() -> None:
    from updater import parse_release
    mock = {
        "tag_name": "v1.2.0",
        "name": "Setlist Manager 1.2.0",
        "html_url": "https://github.com/foo/bar/releases/tag/v1.2.0",
        "body": "## Nyheder\n- Auto-update",
        "published_at": "2026-06-05T12:00:00Z",
        "assets": [
            {"name": "SetlistManagerSetup.exe",
             "browser_download_url": "https://x/Setup.exe"},
            {"name": "SetlistManager.exe",
             "browser_download_url": "https://x/Standalone.exe"},
        ],
    }
    info = parse_release(mock, current="1.1.0")
    assert info.latest == "v1.2.0"
    assert info.is_newer is True
    # Foretrækker Setup-filen
    assert info.installer_url == "https://x/Setup.exe"
    assert "SetlistManagerSetup.exe" in info.assets
    assert "SetlistManager.exe" in info.assets
    assert info.body.startswith("## Nyheder")
    print("  updater parse_release (full) OK")


def test_updater_parse_release_prefers_setup_over_plain_exe() -> None:
    from updater import parse_release
    # Standalone først, så Setup — Setup skal vinde
    mock = {"tag_name": "1.0.0", "assets": [
        {"name": "SetlistManager.exe", "browser_download_url": "http://a/x.exe"},
        {"name": "SetlistManagerSetup.exe", "browser_download_url": "http://a/setup.exe"},
    ]}
    info = parse_release(mock, current="0.9.0")
    assert info.installer_url == "http://a/setup.exe"
    print("  updater prefers Setup.exe over standalone OK")


def test_updater_parse_release_fallback_to_plain_exe() -> None:
    from updater import parse_release
    # Kun standalone — så bruges den
    mock = {"tag_name": "1.0.0", "assets": [
        {"name": "SetlistManager.exe", "browser_download_url": "http://a/x.exe"},
    ]}
    info = parse_release(mock, current="0.9.0")
    assert info.installer_url == "http://a/x.exe"
    print("  updater falls back to standalone .exe OK")


def test_updater_parse_release_empty() -> None:
    from updater import parse_release
    info = parse_release({}, current="1.0.0")
    assert info.latest == "0.0.0"
    assert info.is_newer is False
    assert info.installer_url == ""
    print("  updater parse_release (empty) OK")


def test_updater_parse_release_not_dict() -> None:
    from updater import parse_release
    info = parse_release(None, current="1.0.0")  # type: ignore[arg-type]
    assert info.latest == "0.0.0"
    assert info.is_newer is False
    print("  updater parse_release (None) OK")


def test_updater_cache_rate_limiting() -> None:
    """Cache forhindrer at vi spammer GitHub-API'et."""
    import tempfile, pathlib
    from unittest.mock import patch
    import updater
    with tempfile.TemporaryDirectory() as td:
        with patch.object(updater, "_cache_dir", lambda: pathlib.Path(td)):
            # Tom cache → bør tjekke
            assert updater.should_auto_check() is True
            # Marker som tjekket nu
            updater.mark_checked()
            # Bør IKKE tjekke igen lige med det samme
            assert updater.should_auto_check() is False
            # Men efter 25 timer skulle den gerne ville igen
            import time
            future = time.time() + 25 * 3600
            assert updater.should_auto_check(now=future) is True
    print("  updater cache rate-limiting OK")


def test_updater_skip_version() -> None:
    """Bruger kan springe en specifik version over."""
    import tempfile, pathlib
    from unittest.mock import patch
    import updater
    with tempfile.TemporaryDirectory() as td:
        with patch.object(updater, "_cache_dir", lambda: pathlib.Path(td)):
            assert updater.is_skipped("1.5.0") is False
            updater.mark_skipped("1.5.0")
            assert updater.is_skipped("1.5.0") is True
            # Andre versioner er stadig ikke skippet
            assert updater.is_skipped("1.6.0") is False
    print("  updater skip-version OK")


def test_updater_check_returns_none_on_network_error() -> None:
    """check_for_update må aldrig crashe — fejl giver None."""
    import urllib.error
    from unittest.mock import patch
    import updater
    fake_err = urllib.error.URLError("ingen netværk")
    with patch.object(updater, "_fetch_latest_release", side_effect=fake_err):
        result = updater.check_for_update(timeout=1)
    assert result is None
    print("  updater returns None on network error OK")


def test_updater_records_last_error_on_failure() -> None:
    """Når et tjek fejler skal updater.last_error indeholde en meningsfuld
    grund — så GUI'en kan vise hvorfor det fejlede i stedet for bare
    'ingen forbindelse'.
    """
    import urllib.error
    import ssl
    from unittest.mock import patch
    import updater

    # 1) Netværksfejl
    with patch.object(updater, "_fetch_latest_release",
                     side_effect=urllib.error.URLError("connection refused")):
        result = updater.check_for_update(timeout=1)
    assert result is None
    assert "connection refused" in updater.last_error.lower() or \
           "netværk" in updater.last_error.lower()

    # 2) SSL-fejl (typisk på Windows uden CA-certs)
    with patch.object(updater, "_fetch_latest_release",
                     side_effect=ssl.SSLError("CERTIFICATE_VERIFY_FAILED")):
        result = updater.check_for_update(timeout=1)
    assert result is None
    assert "ssl" in updater.last_error.lower() or \
           "certificate" in updater.last_error.lower()

    # 3) Success — fejl skal ryddes
    with patch.object(updater, "_fetch_latest_release",
                     return_value={"tag_name": "v1.0.0"}):
        result = updater.check_for_update(current="1.0.0")
    assert result is not None
    assert updater.last_error == ""
    print("  updater records last_error on failure OK")


def test_updater_ssl_context_builder_returns_list() -> None:
    """_build_ssl_contexts skal altid returnere mindst én strategi
    (medmindre Python er bygget uden ssl-modul, hvilket aldrig sker)."""
    import updater
    contexts = updater._build_ssl_contexts()
    assert isinstance(contexts, list)
    assert len(contexts) >= 1, "Mindst én SSL-strategi skal være tilgængelig"
    print(f"  updater SSL context builder OK ({len(contexts)} strategier)")


def test_updater_check_returns_info_on_success() -> None:
    """check_for_update returnerer en UpdateInfo ved success."""
    from unittest.mock import patch
    import updater
    fake_json = {
        "tag_name": "v9.9.9",
        "html_url": "http://example.com",
        "assets": [{"name": "SetlistManagerSetup.exe",
                    "browser_download_url": "http://example.com/setup.exe"}],
    }
    with patch.object(updater, "_fetch_latest_release", return_value=fake_json):
        result = updater.check_for_update(current="1.0.0")
    assert result is not None
    assert result.latest == "v9.9.9"
    assert result.is_newer is True
    assert result.installer_url == "http://example.com/setup.exe"
    print("  updater returns UpdateInfo on success OK")


def test_updater_check_handles_404_gracefully() -> None:
    """404 (intet release endnu) skal ikke crashe — returnerer 'ingen ny version'."""
    import urllib.error
    from unittest.mock import patch
    import updater
    err = urllib.error.HTTPError(
        url="x", code=404, msg="Not Found", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    with patch.object(updater, "_fetch_latest_release", side_effect=err):
        result = updater.check_for_update(current="1.0.0")
    assert result is not None
    assert result.is_newer is False
    print("  updater handles 404 gracefully OK")


def test_version_module_has_required_fields() -> None:
    """version.py skal have de tre nødvendige konstanter."""
    import version
    assert hasattr(version, "APP_VERSION")
    assert isinstance(version.APP_VERSION, str) and version.APP_VERSION
    assert hasattr(version, "GITHUB_OWNER")
    assert hasattr(version, "GITHUB_REPO")
    # Version skal være parsbar
    from updater import parse_version
    parts = parse_version(version.APP_VERSION)
    assert parts != (0, 0, 0), f"version.py APP_VERSION='{version.APP_VERSION}' kan ikke parses"
    print("  version.py has all required fields OK")


# ===========================================================================
def run_all() -> None:
    tests = [
        test_basic_save_load_roundtrip,
        test_song_fields_preserved,
        test_multiple_setlists,
        test_cannot_delete_last_setlist,
        test_multiple_bands,
        test_cannot_delete_last_band,
        test_delete_band_adjusts_active,
        test_rename_band,
        test_search_in_current_band_only,
        test_search_all_bands,
        test_copy_song_to_current_band,
        test_print_options_default,
        test_print_options_persisted,
        test_html_export_all_columns,
        test_html_export_minimal_columns,
        test_html_includes_band_name,
        test_v1_migration,
        test_v2_migration,
        test_rename_song_updates_setlists_in_current_band,
        test_delete_song_removes_from_band_setlists,
        test_move_operations,
        test_duration_helpers,
        test_new_song_factory_strips_whitespace,
        test_each_band_has_independent_setlists,
        test_music_search_format_duration,
        test_music_search_format_artist_label,
        test_music_search_make_recording,
        test_music_search_is_live_version,
        test_music_search_filter_out_live,
        test_band_logo_set_clear_get,
        test_band_logo_persisted_per_band,
        test_band_logo_saved_to_disk,
        test_print_options_includes_font_size_and_logo,
        test_font_size_persisted,
        test_html_contains_logo_when_set_and_show_logo_true,
        test_html_omits_logo_when_show_logo_false,
        test_html_omits_logo_when_band_has_no_logo,
        test_html_font_size_changes_title_size,
        test_is_in_current_setlist,
        test_add_to_setlist_returns_bool_and_blocks_duplicates,
        test_font_sizes_pt_has_five_levels,
        test_html_uses_xsmall_and_xlarge_correctly,
        test_html_falls_back_for_unknown_font_size,
        test_marker_helpers,
        test_add_marker_to_setlist,
        test_update_marker_label,
        test_marker_not_counted_as_song,
        test_marker_survives_rename_and_delete,
        test_marker_persists_to_disk,
        test_html_renders_markers_when_show_markers_true,
        test_html_omits_markers_when_show_markers_false,
        test_html_show_title_toggle,
        test_html_show_meta_toggle,
        test_html_show_date_toggle,
        test_html_show_table_header_toggle,
        test_all_print_options_persisted,
        test_old_setlist_format_still_works,
        test_regression_markers_do_not_break_set_construction,
        test_regression_can_add_song_after_marker,
        test_regression_notes_field_used_in_html_print,
        test_updater_parse_version,
        test_updater_is_newer,
        test_updater_parse_release_full,
        test_updater_parse_release_prefers_setup_over_plain_exe,
        test_updater_parse_release_fallback_to_plain_exe,
        test_updater_parse_release_empty,
        test_updater_parse_release_not_dict,
        test_updater_cache_rate_limiting,
        test_updater_skip_version,
        test_updater_check_returns_none_on_network_error,
        test_updater_records_last_error_on_failure,
        test_updater_ssl_context_builder_returns_list,
        test_updater_check_returns_info_on_success,
        test_updater_check_handles_404_gracefully,
        test_version_module_has_required_fields,
    ]
    print(f"Running {len(tests)} tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed ✅")


if __name__ == "__main__":
    run_all()
