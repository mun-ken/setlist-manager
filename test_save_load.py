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


def test_regression_notes_persist_after_edit() -> None:
    """Bug: efter dobbeltklik-redigering af en sang i setlisten,
    skal noterne stadig være gemt korrekt.
    Test simulerer det fulde flow: add → addto setlist → update → reload.
    """
    import tempfile, pathlib
    m = SetlistModel()
    m.add_song("Sang A", duration="3:00", key="C")
    m.add_to_setlist_by_index(0)
    # Brugeren dobbeltklikker → ændrer noter
    ok = m.update_song(
        original_name="Sang A",
        name="Sang A",
        duration="3:00",
        key="C",
        notes="Capo 3 · spil softere på outro",
    )
    assert ok
    # Verificer at noterne nu er på sangen
    assert m.get_song("Sang A")["notes"] == "Capo 3 · spil softere på outro"
    # Verificer at noterne overlever save/load
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "test.json"
        m.save_to_path(str(p))
        m2 = SetlistModel()
        m2.load_from_path(str(p))
        assert m2.get_song("Sang A")["notes"] == "Capo 3 · spil softere på outro"
    # Og at noterne er med i HTML
    opts = default_print_options()
    html = m.generate_html("Test", opts)
    assert "Capo 3" in html
    print("  regression: notes persist after edit + reload OK")


# ===========================================================================
# Feature: Kopiér setliste + "Sidst ændret" timestamp (juni 2026)
# ===========================================================================
def test_duplicate_setlist_basic() -> None:
    """Kopiér setliste skal lave en uafhængig kopi med alle sange + markører."""
    m = SetlistModel()
    m.add_song("Sang A", duration="3:00", key="C")
    m.add_song("Sang B", duration="4:00", key="G")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("EKSTRA-NUMMER")
    m.add_to_setlist_by_index(1)

    assert len(m.setlists) == 1
    new_idx = m.duplicate_setlist(0, "Mit gig 2")
    assert new_idx == 1
    assert len(m.setlists) == 2
    assert m.active_setlist == 1  # kopien er aktiv
    assert m.current_setlist["name"] == "Mit gig 2"
    # Sange + markører skal være kopieret
    assert len(m.current_setlist["songs"]) == 3
    assert m.current_setlist["songs"][0] == "Sang A"
    assert m.current_setlist["songs"][1] == {"marker": "EKSTRA-NUMMER"}
    assert m.current_setlist["songs"][2] == "Sang B"
    print("  duplicate_setlist basic OK")


def test_duplicate_setlist_is_independent() -> None:
    """Ændringer på kopien må IKKE påvirke originalen (deep copy)."""
    m = SetlistModel()
    m.add_song("A"); m.add_song("B"); m.add_song("C")
    m.add_to_setlist_by_index(0)
    m.add_marker_to_setlist("PAUSE")

    m.duplicate_setlist(0)
    # Vi er nu på kopien — tilføj noget
    m.add_to_setlist_by_index(1)
    m.add_to_setlist_by_index(2)
    # Skift tilbage til originalen
    m.set_active(0)
    assert len(m.current_setlist["songs"]) == 2  # Sang A + markør
    # Skift til kopien igen
    m.set_active(1)
    assert len(m.current_setlist["songs"]) == 4  # + Sang B + Sang C
    # Modificer markøren i kopien — originalen må ikke ændres
    m.update_marker_label(1, "ANDET")
    assert m.current_setlist["songs"][1] == {"marker": "ANDET"}
    m.set_active(0)
    assert m.current_setlist["songs"][1] == {"marker": "PAUSE"}, \
        "Markøren i originalen blev ændret — kopien er ikke uafhængig!"
    print("  duplicate_setlist is independent OK")


def test_duplicate_setlist_default_name() -> None:
    """Hvis intet navn er givet → '<original> (kopi)'."""
    m = SetlistModel()
    m.rename_setlist(0, "Sommerfest 2026")
    new_idx = m.duplicate_setlist(0)
    assert m.setlists[new_idx]["name"] == "Sommerfest 2026 (kopi)"
    print("  duplicate_setlist default name OK")


def test_duplicate_setlist_invalid_index() -> None:
    """Ugyldigt index → returnér -1, ingen ændring."""
    m = SetlistModel()
    assert m.duplicate_setlist(99) == -1
    assert m.duplicate_setlist(-1) == -1
    assert len(m.setlists) == 1  # uændret
    print("  duplicate_setlist invalid index OK")


def test_duplicate_setlist_persists_to_disk() -> None:
    """Kopier overlever save/load."""
    import tempfile, pathlib
    m = SetlistModel()
    m.add_song("A"); m.add_song("B")
    m.add_to_setlist_by_index(0)
    m.add_to_setlist_by_index(1)
    m.duplicate_setlist(0, "Kopi-test")

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "t.json"
        m.save_to_path(str(p))
        m2 = SetlistModel()
        m2.load_from_path(str(p))
        assert len(m2.setlists) == 2
        assert m2.setlists[0]["name"] == "Min første setliste"
        assert m2.setlists[1]["name"] == "Kopi-test"
        assert m2.setlists[1]["songs"] == ["A", "B"]
    print("  duplicate_setlist persists to disk OK")


def test_setlist_has_modified_at_field() -> None:
    """Nye setlister skal have modified_at automatisk."""
    m = SetlistModel()
    assert "modified_at" in m.current_setlist
    assert m.current_setlist["modified_at"]  # ikke tom
    # Parsbar som ISO 8601
    from datetime import datetime
    dt = datetime.fromisoformat(m.current_setlist["modified_at"])
    assert dt.year >= 2026
    print("  setlist has modified_at field OK")


def test_touch_setlist_called_on_mutations() -> None:
    """Alle mutating operations skal opdatere modified_at."""
    import time
    m = SetlistModel()
    m.add_song("A")
    m.add_song("B")
    initial_modified = m.get_setlist_modified_at()
    assert initial_modified

    # add_to_setlist_by_index → touch
    time.sleep(1.01)
    m.add_to_setlist_by_index(0)
    after_add = m.get_setlist_modified_at()
    assert after_add > initial_modified, "add_to_setlist_by_index skal touche"

    # add_marker_to_setlist → touch
    time.sleep(1.01)
    m.add_marker_to_setlist("PAUSE")
    after_marker = m.get_setlist_modified_at()
    assert after_marker > after_add, "add_marker_to_setlist skal touche"

    # move_down → touch (hvis der faktisk er ændring)
    time.sleep(1.01)
    m.add_to_setlist_by_index(1)
    before_move = m.get_setlist_modified_at()
    time.sleep(1.01)
    m.move_up(2)
    assert m.get_setlist_modified_at() > before_move, "move_up skal touche"

    # remove_from_setlist_by_index → touch
    time.sleep(1.01)
    before_remove = m.get_setlist_modified_at()
    m.remove_from_setlist_by_index(0)
    assert m.get_setlist_modified_at() > before_remove, "remove skal touche"

    # rename_setlist → touch
    time.sleep(1.01)
    before_rename = m.get_setlist_modified_at()
    m.rename_setlist(0, "Nyt navn")
    assert m.get_setlist_modified_at() > before_rename, "rename skal touche"

    # clear_current_setlist → touch
    time.sleep(1.01)
    before_clear = m.get_setlist_modified_at()
    m.clear_current_setlist()
    assert m.get_setlist_modified_at() > before_clear, "clear skal touche"
    print("  touch_setlist called on all mutations OK")


def test_set_active_does_NOT_touch() -> None:
    """At skifte mellem setlister må IKKE opdatere modified_at."""
    import time
    m = SetlistModel()
    m.add_song("A")
    m.add_to_setlist_by_index(0)
    m.add_setlist("Sæt 2")  # gør Sæt 2 aktiv
    original_modified_sl0 = m.setlists[0]["modified_at"]

    time.sleep(0.1)
    m.set_active(0)  # skift tilbage til den første
    time.sleep(0.1)
    m.set_active(1)  # og tilbage igen
    # modified_at på sl 0 skal være uændret (vi rørte ikke indholdet)
    assert m.setlists[0]["modified_at"] == original_modified_sl0
    print("  set_active does NOT touch modified_at OK")


def test_modified_at_persists_to_disk() -> None:
    """modified_at skal overleve save/load uændret."""
    import tempfile, pathlib
    m = SetlistModel()
    m.add_song("A")
    m.add_to_setlist_by_index(0)
    saved_modified = m.get_setlist_modified_at()

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "t.json"
        m.save_to_path(str(p))
        m2 = SetlistModel()
        m2.load_from_path(str(p))
        assert m2.get_setlist_modified_at() == saved_modified
    print("  modified_at persists to disk OK")


def test_modified_at_migrates_from_old_files() -> None:
    """Setlister fra v1/v2 (uden modified_at) skal få tom string,
    så vi ikke gætter en falsk dato. UI viser bare ingen 'Sidst ændret:'."""
    import tempfile, pathlib, json
    # Lav en v2-fil uden modified_at
    old_data = {
        "schema_version": 2,
        "library": [{"name": "Sang A", "duration": "3:00", "key": "C", "notes": ""}],
        "setlists": [{"name": "Gammel", "songs": ["Sang A"]}],  # INGEN modified_at
        "active_setlist": 0,
    }
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "old.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(old_data, f)
        m = SetlistModel()
        m.load_from_path(str(p))
        assert m.get_setlist_modified_at() == ""
        # Når brugeren ændrer noget skal den så få en timestamp
        m.add_marker_to_setlist("PAUSE")
        assert m.get_setlist_modified_at() != ""
    print("  modified_at migrates gracefully from old files OK")


def test_format_modified_at_human_readable() -> None:
    """format_modified_at skal returnere pænt dansk format."""
    from datetime import datetime, timezone, timedelta
    from setlist_model import format_modified_at

    # Tom string → tom string
    assert format_modified_at("") == ""
    assert format_modified_at("ikke-en-dato") == ""

    # I dag
    now = datetime(2026, 6, 5, 22, 15, tzinfo=timezone.utc)
    today_iso = datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc).isoformat()
    result = format_modified_at(today_iso, now=now)
    assert "i dag" in result
    assert "kl." in result

    # I går
    yesterday_iso = datetime(2026, 6, 4, 14, 30, tzinfo=timezone.utc).isoformat()
    result = format_modified_at(yesterday_iso, now=now)
    assert "i går" in result

    # Tidligere på året
    old_iso = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc).isoformat()
    result = format_modified_at(old_iso, now=now)
    assert "marts" in result
    assert "2026" not in result  # samme år → ingen år

    # Sidste år
    last_year_iso = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc).isoformat()
    result = format_modified_at(last_year_iso, now=now)
    assert "marts" in result
    assert "2024" in result
    print("  format_modified_at produces human Danish text OK")


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


def test_updater_installer_filename_from_url() -> None:
    """installer_filename_from_url skal trække filnavnet ud af en GitHub
    release download-URL, og falde tilbage til defaultnavn ved tom/ugyldig
    URL."""
    import updater
    # Almindelig case
    assert updater.installer_filename_from_url(
        "https://github.com/x/y/releases/download/v1.2.0/SetlistManagerSetup-1.2.0.exe"
    ) == "SetlistManagerSetup-1.2.0.exe"
    # URL der ender på slash → fallback
    assert updater.installer_filename_from_url("https://x.com/dir/") == "SetlistManagerSetup.exe"
    # Tom URL → fallback
    assert updater.installer_filename_from_url("") == "SetlistManagerSetup.exe"
    # Custom fallback respekteres
    assert updater.installer_filename_from_url("", fallback="custom.msi") == "custom.msi"
    # Query-string ignoreres
    assert updater.installer_filename_from_url(
        "https://x.com/file.exe?token=abc"
    ) == "file.exe"
    print("  updater.installer_filename_from_url OK")


def test_updater_default_download_dir_creates_dir() -> None:
    """default_download_dir skal returnere en Path under systemets temp-dir,
    og oprette den hvis den ikke findes."""
    from pathlib import Path
    import updater

    d = updater.default_download_dir()
    assert isinstance(d, Path)
    assert d.exists(), "default_download_dir skal oprette directory hvis det mangler"
    assert d.is_dir()
    # Skal være under temp
    import tempfile
    assert str(d).startswith(tempfile.gettempdir())
    print(f"  updater.default_download_dir OK ({d})")


def test_updater_download_file_writes_atomically() -> None:
    """download_file skal:
    1. Skrive til en .partial-fil først
    2. Rename atomisk til target-filen ved success
    3. Kalde progress_callback undervejs
    """
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    import tempfile, io
    import updater

    test_content = b"hello world " * 1000  # 12000 bytes
    progress_calls = []

    def fake_progress(d: int, t: int) -> None:
        progress_calls.append((d, t))

    # Mock urlopen
    fake_response = MagicMock()
    fake_response.headers = {"Content-Length": str(len(test_content))}
    fake_response.read = MagicMock(
        side_effect=[test_content[:5000], test_content[5000:], b""]
    )
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "downloaded.bin"
        partial = dest.with_suffix(dest.suffix + ".partial")

        with patch("urllib.request.urlopen", return_value=fake_response):
            ok = updater.download_file(
                "https://example.com/file.bin",
                dest,
                progress_callback=fake_progress,
                chunk_size=5000,
            )

        assert ok is True, f"download skulle lykkes, last_error={updater.last_error!r}"
        assert dest.exists(), "Target-fil skal findes efter download"
        assert not partial.exists(), ".partial-fil skal være væk efter atomisk rename"
        assert dest.read_bytes() == test_content
        assert len(progress_calls) >= 1, "progress_callback skulle kaldes mindst en gang"
        # Sidste kald skal vise færdig download
        last_d, last_t = progress_calls[-1]
        assert last_d == len(test_content)
        assert last_t == len(test_content)
        print(f"  updater.download_file writes atomically OK ({len(progress_calls)} progress)")


def test_updater_download_file_handles_network_error() -> None:
    """download_file skal returnere False og sætte last_error når netværket
    fejler — uden at efterlade en korrupt fil."""
    from pathlib import Path
    from unittest.mock import patch
    import urllib.error, tempfile
    import updater

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "should_not_exist.bin"
        partial = dest.with_suffix(dest.suffix + ".partial")

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            ok = updater.download_file("https://example.com/x", dest)

        assert ok is False
        assert not dest.exists(), "Korrupt fil må IKKE blive liggende"
        assert not partial.exists(), ".partial skal ryddes op efter fejl"
        assert updater.last_error, "last_error skal sættes ved fejl"
        print(f"  updater.download_file network error OK ({updater.last_error!r})")


def test_updater_download_file_handles_ssl_error() -> None:
    """SSL-fejl skal fanges og rapporteres — ikke crashe."""
    from pathlib import Path
    from unittest.mock import patch
    import ssl, tempfile
    import updater

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "ssl_test.bin"

        with patch(
            "urllib.request.urlopen",
            side_effect=ssl.SSLError("CERTIFICATE_VERIFY_FAILED"),
        ):
            ok = updater.download_file("https://example.com/x", dest)

        assert ok is False
        assert not dest.exists()
        # SSL-fejl skal nævnes
        err = updater.last_error.lower()
        assert "ssl" in err or "certificate" in err or "verify" in err, \
            f"last_error skulle nævne SSL: {updater.last_error!r}"
        print(f"  updater.download_file SSL error OK")


def test_updater_launch_installer_returns_false_when_missing() -> None:
    """launch_installer skal returnere False hvis filen ikke eksisterer,
    og sætte last_error — ikke crashe."""
    from pathlib import Path
    import updater
    fake = Path("/tmp/definitely_does_not_exist_12345.exe")
    assert not fake.exists()
    ok = updater.launch_installer(fake)
    assert ok is False
    assert updater.last_error, "last_error skal sættes"
    assert "ikke" in updater.last_error.lower() or "not" in updater.last_error.lower() \
        or "findes" in updater.last_error.lower()
    print("  updater.launch_installer missing-file OK")


def test_updater_launch_installer_calls_correct_command_on_unix() -> None:
    """På macOS/Linux skal launch_installer kalde subprocess.Popen med
    start_new_session=True så installeren detacher fra vores proces.

    (Funktionen er primært til Windows, men vi vil teste subprocess-kaldet
    uden faktisk at køre noget.)
    """
    import sys, tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    import updater

    if sys.platform.startswith("win"):
        # På Windows kalder den os.startfile() — test den i stedet
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            with patch("os.startfile") as mock_start:
                ok = updater.launch_installer(tmp_path, silent=False)
            assert ok is True
            mock_start.assert_called_once_with(str(tmp_path))
            print("  updater.launch_installer Windows os.startfile OK")
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        # macOS/Linux: subprocess.Popen
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            with patch("subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock()
                ok = updater.launch_installer(tmp_path)
            assert ok is True
            mock_popen.assert_called_once()
            # Tjek start_new_session=True er sat
            _, kwargs = mock_popen.call_args
            assert kwargs.get("start_new_session") is True, \
                "Skal detache med start_new_session=True"
            print("  updater.launch_installer Unix Popen OK")
        finally:
            tmp_path.unlink(missing_ok=True)


def test_updater_launch_installer_silent_uses_inno_flags() -> None:
    """Silent mode på Windows skal sende /SILENT — men IKKE
    /CLOSEAPPLICATIONS eller /RESTARTAPPLICATIONS. De flags skabte race
    condition med PyInstaller --onefile's _MEI temp-mappe (resulterede i
    'Failed to load Python DLL'-fejl ved auto-genstart).
    """
    import sys, tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    import updater

    if not sys.platform.startswith("win"):
        # Test logikken via patch på subprocess.Popen direkte
        # Vi simulerer Windows-grenen ved at patche sys.platform
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            with patch.object(updater, "sys") as mock_sys, \
                 patch("subprocess.Popen") as mock_popen:
                mock_sys.platform = "win32"
                mock_popen.return_value = MagicMock()
                ok = updater.launch_installer(tmp_path, silent=True)

            assert ok is True
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd = args[0]
            assert "/SILENT" in cmd
            # Disse flags må IKKE være der — de skabte race condition
            assert "/CLOSEAPPLICATIONS" not in cmd, \
                "CLOSEAPPLICATIONS skabte race med PyInstaller _MEI cleanup"
            assert "/RESTARTAPPLICATIONS" not in cmd, \
                "RESTARTAPPLICATIONS gav 'Failed to load Python DLL'-fejl"
            print("  updater.launch_installer silent-flags OK")
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        # Rigtig Windows — kan ikke patche sys så nemt, skip
        print("  updater.launch_installer silent-flags (skipped on real Windows)")


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


# ---------------------------------------------------------------------------
# Theme + Stage Mode tests
# ---------------------------------------------------------------------------
def _tk_available() -> bool:
    """True hvis vi kan instantiere et Tk-vindue på denne maskine.

    På macOS med /usr/bin/python3 kan tk være broken (kræver nyere macOS-version).
    På CI uden display vil Tk() også fejle. I begge tilfælde springer vi
    GUI-tests over så test-suite kører grønt."""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


_TK_OK = _tk_available()


def _tkinter_importable() -> bool:
    """True hvis tkinter overhovedet kan importeres (Python built with Tk)."""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


_TKINTER_OK = _tkinter_importable()


def test_theme_module_loads() -> None:
    """theme.py kan importeres og har de forventede klasser/funktioner."""
    if not _TKINTER_OK:
        print("  theme module loads (skipped — Python uden tkinter)")
        return
    import theme
    # Klasser
    assert hasattr(theme, "Colors")
    assert hasattr(theme, "Fonts")
    # Funktioner
    assert callable(theme.apply_theme)
    assert callable(theme.style_listbox)
    assert callable(theme.style_text)
    # Vigtige farver der bruges af main.py
    for color_name in (
        "BG", "SURFACE", "TEXT", "ACCENT", "BORDER",
        "MARKER_BG", "MARKER_FG", "MARKER_SELECTED_BG", "MARKER_SELECTED_FG",
        "IN_SETLIST_FG", "SELECTED_BG",
    ):
        c = getattr(theme.Colors, color_name)
        assert isinstance(c, str) and c.startswith("#"), \
            f"theme.Colors.{color_name} skal være en hex-farve, fik {c!r}"
    print("  theme module loads OK")


def test_theme_apply_does_not_crash() -> None:
    """apply_theme på en headless Tk skal ikke crashe."""
    if not _TK_OK:
        print("  theme apply (skipped — Tk not available)")
        return
    import tkinter as tk
    import theme
    root = tk.Tk()
    try:
        theme.apply_theme(root)
        # Verificér at clam-temaet er aktivt
        from tkinter import ttk
        style = ttk.Style(root)
        assert style.theme_use() == "clam"
        print("  theme.apply_theme OK")
    finally:
        root.destroy()


def test_stage_mode_module_loads() -> None:
    """stage_mode.py kan importeres og har StageMode-klassen."""
    if not _TKINTER_OK:
        print("  stage_mode module loads (skipped — Python uden tkinter)")
        return
    import stage_mode
    assert hasattr(stage_mode, "StageMode")
    assert hasattr(stage_mode, "StageColors")
    # StageMode er en Toplevel-subclass — men import af tkinter kan
    # crashe på broken macOS, så vi skipper denne check hvis det er tilfældet
    if _TK_OK:
        import tkinter as tk
        assert issubclass(stage_mode.StageMode, tk.Toplevel)
    print("  stage_mode module loads OK")


def test_stage_mode_navigation_skips_markers() -> None:
    """Stage Mode skal hoppe over markører ved Next/Prev sang."""
    if not _TK_OK:
        print("  stage_mode navigation (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel, make_marker

    root = tk.Tk()
    root.withdraw()  # usynlig

    try:
        # Opbyg en model med: sang1, MARKER, sang2, sang3, MARKER, sang4
        model = SetlistModel()
        for n in ("A", "B", "C", "D"):
            model.add_song(n)
        sl = model.current_setlist
        sl["songs"] = ["A", make_marker("PAUSE"), "B", "C",
                       make_marker("EKSTRA"), "D"]

        # Patch fullscreen så vi ikke maxer vinduet under test
        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False  # ignorer fullscreen-kald
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, start_index=0)
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # Start: index 0 (sang A)
            assert sm.current_idx == 0
            # Next → skip marker @1 → index 2 (sang B)
            sm.next_song()
            assert sm.current_idx == 2, f"expected 2, got {sm.current_idx}"
            # Next → index 3 (sang C)
            sm.next_song()
            assert sm.current_idx == 3
            # Next → skip marker @4 → index 5 (sang D)
            sm.next_song()
            assert sm.current_idx == 5
            # Next ved sidste sang → ingen ændring
            sm.next_song()
            assert sm.current_idx == 5
            # Prev → skip marker @4 → index 3 (sang C)
            sm.prev_song()
            assert sm.current_idx == 3
            # Prev → index 2 (sang B)
            sm.prev_song()
            assert sm.current_idx == 2
            # Prev → skip marker @1 → index 0 (sang A)
            sm.prev_song()
            assert sm.current_idx == 0
            # Prev ved første sang → ingen ændring
            sm.prev_song()
            assert sm.current_idx == 0
        finally:
            sm.close()
        print("  stage_mode navigation skips markers OK")
    finally:
        root.destroy()


def test_stage_mode_start_index_on_marker_skips_forward() -> None:
    """Hvis start_index peger på en markør, skal Stage Mode hoppe frem
    til første rigtige sang."""
    if not _TK_OK:
        print("  stage_mode start-on-marker (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel, make_marker

    root = tk.Tk()
    root.withdraw()

    try:
        model = SetlistModel()
        for n in ("X", "Y"):
            model.add_song(n)
        sl = model.current_setlist
        # [MARKER, X, Y] — start_index=0 peger på markør
        sl["songs"] = [make_marker("INTRO"), "X", "Y"]

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, start_index=0)
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # Skal være hoppet frem til index 1 (sang X)
            assert sm.current_idx == 1
        finally:
            sm.close()
        print("  stage_mode start-on-marker skips forward OK")
    finally:
        root.destroy()


def test_stage_mode_go_to_song_number() -> None:
    """go_to_song_number(N) skal hoppe til sang nummer N (1-baseret,
    markører tæller ikke)."""
    if not _TK_OK:
        print("  stage_mode go_to_song_number (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel, make_marker

    root = tk.Tk()
    root.withdraw()

    try:
        model = SetlistModel()
        for n in ("A", "B", "C", "D"):
            model.add_song(n)
        sl = model.current_setlist
        # [A, MARKER, B, C, MARKER, D] → song 1=A, 2=B, 3=C, 4=D
        sl["songs"] = ["A", make_marker("M1"), "B", "C", make_marker("M2"), "D"]

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, start_index=0)
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # Sang 4 = D = index 5
            sm.go_to_song_number(4)
            assert sm.current_idx == 5
            # Sang 2 = B = index 2
            sm.go_to_song_number(2)
            assert sm.current_idx == 2
            # Sang 1 = A = index 0
            sm.go_to_song_number(1)
            assert sm.current_idx == 0
            # Sang 99 = no-op (uden ændring)
            sm.go_to_song_number(99)
            assert sm.current_idx == 0
        finally:
            sm.close()
        print("  stage_mode go_to_song_number OK")
    finally:
        root.destroy()


def test_stage_mode_supports_window_mode() -> None:
    """Stage Mode skal kunne åbnes i 'window' mode (ikke fullscreen).

    I window-mode skal vinduet være resizable og IKKE have -fullscreen sat.
    """
    if not _TK_OK:
        print("  stage_mode window-mode (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()

    try:
        model = SetlistModel()
        # VIGTIGT: add_song tilføjer kun til biblioteket — vi skal også
        # have sangen i setlisten ellers returnerer StageMode tidligt
        model.add_song("X")
        model.current_setlist["songs"] = ["X"]

        # Patch attributes så vi kan tracke fullscreen-kald
        fullscreen_calls = []
        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                if len(args) > 1:
                    fullscreen_calls.append(args[1])
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            # 1) Test window-mode — må IKKE kalde attributes("-fullscreen", True)
            sm = stage_mode.StageMode(root, model, mode="window")
            assert sm.mode == "window"
            assert sm._is_fullscreen is False, \
                "I window-mode skal _is_fullscreen være False"
            # Ingen True-kald til fullscreen
            assert True not in fullscreen_calls, \
                f"window-mode skal IKKE aktivere fullscreen — fik {fullscreen_calls!r}"
            sm.close()
            fullscreen_calls.clear()

            # 2) Test fullscreen-mode (default) — SKAL kalde med True
            sm = stage_mode.StageMode(root, model, mode="fullscreen")
            assert sm.mode == "fullscreen"
            # I fullscreen-mode skal _is_fullscreen være True
            # (men fake_attributes returnerer False, så hvis vi ikke har
            # ramt except-grenen, er True blevet bedt om)
            assert True in fullscreen_calls, \
                f"fullscreen-mode skal aktivere fullscreen — fik {fullscreen_calls!r}"
            sm.close()
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]
        print("  stage_mode supports window-mode OK")
    finally:
        root.destroy()


def test_stage_mode_font_scales_with_window_size() -> None:
    """Stage Mode skal skalere fonts efter vinduehøjden.

    Ved REF_HEIGHT (1000px) får vi BASE_FONTS sizes.
    Halv størrelse → halv font (modulo min-grænse).
    Dobbelt størrelse → dobbelt font (modulo max-grænse).
    """
    if not _TK_OK:
        print("  stage_mode font scaling (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()

    try:
        model = SetlistModel()
        model.add_song("A")
        # VIGTIGT: tilføj også til setlisten (add_song er kun bibliotek)
        model.current_setlist["songs"] = ["A"]

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, mode="window")
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            ref = stage_mode.StageMode.REF_HEIGHT
            base = stage_mode.StageMode.BASE_FONTS["current_main"]  # 72

            # Mock winfo_height så vi kan styre skalering deterministisk
            def fake_height(h):
                return lambda: h

            # 1.0 scale = REF_HEIGHT
            sm.winfo_height = fake_height(ref)  # type: ignore[method-assign]
            assert sm._scale() == 1.0
            font = sm._font("current_main", weight="bold")
            assert font[1] == base, f"At ref-height: expected {base}, got {font[1]}"

            # 0.5 scale = halv height
            sm.winfo_height = fake_height(ref // 2)  # type: ignore[method-assign]
            assert sm._scale() == 0.5
            font = sm._font("current_main")
            assert font[1] == base // 2, f"At half: expected {base//2}, got {font[1]}"

            # Min-grænse: meget lille vindue. NB: _scale() har et guard
            # 'if h < 100: return 1.0' (for at undgå crash på ikke-initialiseret
            # vindue), så vi bruger h=200 der giver naturligt 0.20 → capped til
            # MIN_SCALE (0.35).
            sm.winfo_height = fake_height(200)  # type: ignore[method-assign]
            assert sm._scale() == stage_mode.StageMode.MIN_SCALE, \
                f"Expected MIN_SCALE ({stage_mode.StageMode.MIN_SCALE}), got {sm._scale()}"
            font = sm._font("current_main")
            min_expected = int(base * stage_mode.StageMode.MIN_SCALE)
            assert font[1] == min_expected, \
                f"At min-grænse: expected {min_expected}, got {font[1]}"

            # Uninitialiseret vindue (h < 100) → returnerer 1.0 som fallback
            sm.winfo_height = fake_height(0)  # type: ignore[method-assign]
            assert sm._scale() == 1.0, \
                "Ved h<100 (vindue ikke ready) skal _scale returnere 1.0 som safe default"

            # Max-grænse: kæmpe vindue
            sm.winfo_height = fake_height(10000)  # type: ignore[method-assign]
            assert sm._scale() == stage_mode.StageMode.MAX_SCALE
            font = sm._font("current_main")
            max_expected = int(base * stage_mode.StageMode.MAX_SCALE)
            assert font[1] == max_expected, \
                f"At max-grænse: expected {max_expected}, got {font[1]}"

            # Font-tuple struktur: ("Segoe UI", size) eller (..., "bold")
            font = sm._font("current_main", weight="bold")
            assert font[0] == stage_mode.StageMode.FONT_FAMILY
            assert font[2] == "bold"

            # Italic + bold
            font = sm._font("marker", weight="bold", italic=True)
            assert "bold" in font[2] and "italic" in font[2]
        finally:
            sm.close()
        print("  stage_mode font scales with window size OK")
    finally:
        root.destroy()


def test_stage_mode_scroll_uses_correct_fraction_formula() -> None:
    """Regression-test for scroll-bug der klippede toppen af current song.

    yview_moveto(fraction) tolker fraction relativt til den FULDE
    scroll-region (inner_h), IKKE til max-scrollable (inner_h - canvas_h).
    Tidligere kode delte target_y med max_y i stedet for inner_h
    → scroll-position blev (inner_h/max_y)× for langt nede → toppen af
    current-row blev klippet.

    Vi tester ved at mocke canvas/inner geometri + capture'r hvilken
    fraction der bliver givet til yview_moveto.
    """
    if not _TK_OK:
        print("  stage_mode scroll formula (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()

    try:
        model = SetlistModel()
        # 20 sange så vi kan teste scrolling
        for i in range(20):
            model.add_song(f"Sang {i+1}")
        model.current_setlist["songs"] = [f"Sang {i+1}" for i in range(20)]

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, start_index=10, mode="window")
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # Mock canvas/inner geometri til kendte værdier
            INNER_H = 2000   # total content height
            CANVAS_H = 600   # viewport height
            WIDGET_Y = 900   # current row's y-position i inner
            WIDGET_H = 130   # current row's height

            # Capture alle yview_moveto-kald
            calls = []
            class FakeCanvas:
                def configure(self, **kw): pass
                def bbox(self, _): return (0, 0, 100, INNER_H)
                def winfo_height(self): return CANVAS_H
                def yview_moveto(self, frac): calls.append(frac)
                def yview(self): return (calls[-1] if calls else 0.0, 1.0)
                def yview_scroll(self, n, what): pass

            class FakeInner:
                def winfo_height(self): return INNER_H

            class FakeWidget:
                def winfo_y(self): return WIDGET_Y
                def winfo_height(self): return WIDGET_H

            sm.canvas = FakeCanvas()  # type: ignore[assignment]
            sm.inner = FakeInner()  # type: ignore[assignment]
            sm.song_widgets = [FakeWidget()] * 20  # type: ignore[list-item]
            sm.current_idx = 10

            sm._scroll_to_current()

            assert calls, "yview_moveto blev aldrig kaldt"
            actual_fraction = calls[0]
            actual_viewport_top = actual_fraction * INNER_H

            # Current row's top er ved y=900. Toppen MÅ IKKE klippes.
            # Dvs viewport_top SKAL være ≤ 900 (med en margin).
            assert actual_viewport_top <= WIDGET_Y, (
                f"BUG: viewport_top={actual_viewport_top} > widget_y={WIDGET_Y} "
                f"→ toppen af current-row klippes! "
                f"Bug-symptom: 'man kan ikke se sangen i live'. "
                f"Fraction givet til yview_moveto: {actual_fraction}, "
                f"forventet ≤ {WIDGET_Y/INNER_H:.4f}"
            )

            # Den GAMLE buggy formel ville give fraction = target_y / max_y
            # = (900 - 200) / (2000 - 600) = 700/1400 = 0.5
            # → viewport_top = 0.5 × 2000 = 1000 → WIDGET_Y=900 ville være klippet
            # Den NYE formel: fraction = target_y / inner_h = 700/2000 = 0.35
            # → viewport_top = 0.35 × 2000 = 700 → WIDGET_Y=900 ligger 200px nede
            # i viewport, perfekt synlig.
            BUGGY_FRACTION = 0.5
            assert abs(actual_fraction - BUGGY_FRACTION) > 0.05, (
                f"Fraction {actual_fraction} matcher den GAMLE buggy "
                f"formel target_y/max_y={BUGGY_FRACTION}. "
                f"Formlen skal være target_y/inner_h."
            )

            print(f"  stage_mode scroll formula OK "
                  f"(fraction={actual_fraction:.4f}, viewport_top={actual_viewport_top:.0f}px)")
        finally:
            sm.close()
    finally:
        root.destroy()


# ===========================================================================
#  Hotkeys module tests
# ===========================================================================
def test_hotkeys_module_loads() -> None:
    """hotkeys-modulet skal kunne importeres uden fejl."""
    import hotkeys
    assert hasattr(hotkeys, "ACTIONS")
    assert hasattr(hotkeys, "KeyBindings")
    assert hasattr(hotkeys, "format_key")
    assert hasattr(hotkeys, "event_to_binding")
    # Standard-handlinger skal være registreret
    for required in ("next_song", "prev_song", "first_song", "last_song",
                     "toggle_fullscreen", "close"):
        assert required in hotkeys.ACTIONS, f"Mangler action: {required}"
    print("  hotkeys module loads OK")


def test_hotkeys_default_bindings_match_legacy() -> None:
    """Default-bindings skal matche v1.4.7's hardcoded keys så ingen
    brugere mærker en forskel hvis de ikke konfigurerer."""
    from hotkeys import ACTIONS, KeyBindings
    kb = KeyBindings()
    # Næste sang skal stadig være Space + arrows
    nx = kb.get_keys("next_song")
    assert "<space>" in nx
    assert "<Right>" in nx
    assert "<Return>" in nx
    # Forrige
    pv = kb.get_keys("prev_song")
    assert "<Left>" in pv
    assert "<Up>" in pv
    # Close
    cl = kb.get_keys("close")
    assert "<Escape>" in cl
    print("  hotkeys default bindings match legacy OK")


def test_hotkeys_add_remove_reset() -> None:
    """Tilføj, fjern og nulstil et binding."""
    from hotkeys import KeyBindings
    kb = KeyBindings()

    assert kb.is_default("next_song")
    # Tilføj en helt ny tast
    added = kb.add_key("next_song", "<F1>")
    assert added is True
    assert "<F1>" in kb.get_keys("next_song")
    assert not kb.is_default("next_song")

    # Duplikat skal returnere False
    added_again = kb.add_key("next_song", "<F1>")
    assert added_again is False

    # Fjern
    removed = kb.remove_key("next_song", "<F1>")
    assert removed is True
    assert "<F1>" not in kb.get_keys("next_song")

    # Reset til default
    kb.add_key("next_song", "<F2>")
    assert not kb.is_default("next_song")
    kb.reset_action("next_song")
    assert kb.is_default("next_song")
    print("  hotkeys add/remove/reset OK")


def test_hotkeys_find_conflict() -> None:
    """find_conflict skal finde en tast der allerede er bundet andetsteds."""
    from hotkeys import KeyBindings
    kb = KeyBindings()
    # Space er default bundet til next_song
    conflict = kb.find_conflict("<space>")
    assert conflict == "next_song"
    # Hvis vi excluder next_song er der ingen konflikt
    conflict_excluded = kb.find_conflict("<space>", exclude_action="next_song")
    assert conflict_excluded is None
    # En tast der IKKE er bundet
    no_conflict = kb.find_conflict("<F12>")
    assert no_conflict is None
    print("  hotkeys find_conflict OK")


def test_hotkeys_persist_to_disk_and_reload() -> None:
    """save() + load() skal roundtrippe custom bindings."""
    import tempfile
    from pathlib import Path
    from hotkeys import KeyBindings

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hotkeys.json"

        kb = KeyBindings()
        kb.set_keys("next_song", ["<F5>", "<F6>"])
        kb.set_keys("close", ["<F12>"])
        kb.save(path)

        assert path.exists()

        kb2 = KeyBindings.load(path)
        assert kb2.get_keys("next_song") == ["<F5>", "<F6>"]
        assert kb2.get_keys("close") == ["<F12>"]
        # Actions vi IKKE rørte skal stadig være default
        assert kb2.is_default("prev_song")
    print("  hotkeys persist + reload OK")


def test_hotkeys_load_missing_file_returns_defaults() -> None:
    """load() fra ikke-eksisterende fil skal IKKE crashe — bare returnere defaults."""
    from pathlib import Path
    from hotkeys import KeyBindings
    kb = KeyBindings.load(Path("/does/not/exist/hotkeys.json"))
    # Alle actions er default
    for aid in ("next_song", "prev_song", "close"):
        assert kb.is_default(aid)
    print("  hotkeys load missing file OK")


def test_hotkeys_load_corrupt_file_returns_defaults() -> None:
    """load() fra korrupt JSON skal returnere defaults, ikke crashe."""
    import tempfile
    from pathlib import Path
    from hotkeys import KeyBindings

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "corrupt.json"
        path.write_text("not json {{{", encoding="utf-8")
        kb = KeyBindings.load(path)
        assert kb.is_default("next_song")
    print("  hotkeys load corrupt file OK")


def test_hotkeys_load_filters_unknown_actions() -> None:
    """Hvis JSON-filen indeholder en action vi ikke kender (fra anden
    version), skal den ignoreres — ikke crashe."""
    import json, tempfile
    from pathlib import Path
    from hotkeys import KeyBindings

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "future.json"
        path.write_text(json.dumps({
            "next_song": ["<F1>"],
            "future_unknown_action": ["<F2>"],  # ← ukendt
            "another_unknown": "not even a list",  # ← ugyldig type
        }), encoding="utf-8")

        kb = KeyBindings.load(path)
        assert kb.get_keys("next_song") == ["<F1>"]
        # Ukendte actions skal bare være ignoreret
        assert "future_unknown_action" not in kb.to_dict()
    print("  hotkeys load filters unknown actions OK")


def test_hotkeys_format_key_human_readable() -> None:
    """format_key skal gøre Tk-syntaks til pænt dansk."""
    from hotkeys import format_key
    assert format_key("<space>") == "Mellemrum"
    assert format_key("<Return>") == "Enter"
    assert format_key("<Escape>") == "Esc"
    assert format_key("<Right>") == "→ Højre"
    assert format_key("F") == "F"
    assert format_key("a") == "A"
    assert format_key("<F5>") == "F5"
    # Modifier-kombinationer
    assert "Ctrl" in format_key("<Control-s>")
    assert "S" in format_key("<Control-s>")
    print("  hotkeys format_key OK")


def test_hotkeys_event_to_binding_named_keys() -> None:
    """event_to_binding skal omdanne et fake Tk-event til en gemmelig
    binding-streng."""
    from hotkeys import event_to_binding

    class FakeEvent:
        def __init__(self, keysym, char="", state=0):
            self.keysym = keysym
            self.char = char
            self.state = state

    # Mellemrum
    assert event_to_binding(FakeEvent("space", " ")) == "<space>"
    # F-tast
    assert event_to_binding(FakeEvent("F5")) == "<F5>"
    # Pile
    assert event_to_binding(FakeEvent("Right")) == "<Right>"
    # Bogstav uden modifier
    assert event_to_binding(FakeEvent("a", "a")) == "a"
    # Modifier-only events skal returnere None
    assert event_to_binding(FakeEvent("Shift_L", "")) is None
    assert event_to_binding(FakeEvent("Control_L", "")) is None
    # Ctrl+S
    out = event_to_binding(FakeEvent("s", "", state=0x0004))
    assert "Control" in out and "s" in out
    print("  hotkeys event_to_binding OK")


def test_hotkeys_set_keys_dedupes() -> None:
    """set_keys skal strippe duplikater men bevare rækkefølge."""
    from hotkeys import KeyBindings
    kb = KeyBindings()
    kb.set_keys("next_song", ["<F1>", "<F2>", "<F1>", "<F3>", "<F2>"])
    assert kb.get_keys("next_song") == ["<F1>", "<F2>", "<F3>"]
    print("  hotkeys set_keys dedupes OK")


def test_hotkeys_stage_mode_uses_custom_bindings() -> None:
    """Stage Mode skal binde de keys brugeren har sat (ikke kun defaults)."""
    if not _TK_OK:
        print("  stage_mode uses custom bindings (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from hotkeys import KeyBindings
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        model = SetlistModel()
        model.add_song("A")
        model.current_setlist["songs"] = ["A"]

        # Custom bindings: brug F1 som "next" i stedet for Space
        kb = KeyBindings()
        kb.set_keys("next_song", ["<F1>"])
        kb.set_keys("close", ["<F12>"])

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, mode="window", key_bindings=kb)
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # bind() returnerer et bind-script (truthy) hvis bundet, "" hvis ikke
            f1_binding = sm.bind("<F1>")
            f12_binding = sm.bind("<F12>")
            space_binding = sm.bind("<space>")  # ikke længere bundet

            assert f1_binding, "F1 burde være bundet til next_song"
            assert f12_binding, "F12 burde være bundet til close"
            # Space er ikke i kb.get_keys('next_song') → skal IKKE være bundet
            assert not space_binding, \
                f"<space> burde IKKE være bundet når kb kun har F1: got {space_binding!r}"
        finally:
            sm.close()
        print("  stage_mode uses custom bindings OK")
    finally:
        root.destroy()


def test_hotkeys_stage_mode_rebind_changes_live() -> None:
    """rebind_keys() skal opdatere bindings uden at lukke vinduet."""
    if not _TK_OK:
        print("  stage_mode rebind live (skipped — Tk not available)")
        return

    import tkinter as tk
    import stage_mode
    from hotkeys import KeyBindings
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        model = SetlistModel()
        model.add_song("A")
        model.current_setlist["songs"] = ["A"]

        kb_initial = KeyBindings()  # defaults

        original_attributes = tk.Toplevel.attributes
        def fake_attributes(self, *args, **kw):
            if args and args[0] == "-fullscreen":
                return False
            return original_attributes(self, *args, **kw)
        tk.Toplevel.attributes = fake_attributes  # type: ignore[assignment]

        try:
            sm = stage_mode.StageMode(root, model, mode="window", key_bindings=kb_initial)
        finally:
            tk.Toplevel.attributes = original_attributes  # type: ignore[assignment]

        try:
            # Default: <space> bundet
            assert sm.bind("<space>"), "Default skal binde <space>"

            # Skift bindings live
            kb_new = KeyBindings()
            kb_new.set_keys("next_song", ["<F7>"])
            sm.rebind_keys(kb_new)

            assert sm.bind("<F7>"), "Efter rebind skal <F7> være bundet"
            # Space skal nu være UNBOUND
            assert not sm.bind("<space>"), \
                "Efter rebind til F7 skal <space> ikke længere være bundet"
        finally:
            sm.close()
        print("  stage_mode rebind changes live OK")
    finally:
        root.destroy()


# ===========================================================================
#  NDI tests
# ===========================================================================
def test_ndi_output_module_loads() -> None:
    """ndi_output skal kunne importeres uden at crashe — også når NDI Runtime
    ikke er installeret. is_available() skal bare returnere False."""
    import ndi_output
    assert hasattr(ndi_output, "is_available")
    assert hasattr(ndi_output, "NDISender")
    assert hasattr(ndi_output, "NDIError")
    # Bør være en bool uanset om NDI er der eller ej
    result = ndi_output.is_available()
    assert isinstance(result, bool)
    print(f"  ndi_output loads OK (NDI tilgængelig: {result})")


def test_ndi_output_install_help_is_useful() -> None:
    """get_install_help skal returnere noget brugbart selv når NDI ikke er der."""
    import ndi_output
    help_text = ndi_output.get_install_help()
    assert isinstance(help_text, str)
    assert len(help_text) > 20  # ikke bare tom streng
    if not ndi_output.is_available():
        # Skal nævne download-URL'en
        assert "ndi.video" in help_text.lower(), "Hjælp skal nævne ndi.video"
    print("  ndi_output install_help is useful OK")


def test_ndi_output_sender_raises_clear_error_when_unavailable() -> None:
    """Forsøg på at lave NDISender uden NDI installeret skal give en
    pæn NDIError — IKKE en mystisk AttributeError eller importfejl."""
    import ndi_output
    if ndi_output.is_available():
        print("  ndi_sender error raise (skipped — NDI er installeret)")
        return
    try:
        ndi_output.NDISender(name="Test")
        assert False, "Skulle have rejst NDIError"
    except ndi_output.NDIError as e:
        # Fejlbeskeden skal være hjælpsom (indeholde download-link)
        assert "ndi.video" in str(e).lower() or len(str(e)) > 20
        print("  ndi_sender raises clear NDIError when unavailable OK")


def test_ndi_renderer_module_loads() -> None:
    """ndi_renderer skal kunne importeres."""
    import ndi_renderer
    assert hasattr(ndi_renderer, "render_notes_frame")
    assert hasattr(ndi_renderer, "get_current_and_next")
    print("  ndi_renderer loads OK")


def test_ndi_renderer_render_basic_frame() -> None:
    """render_notes_frame skal lave et gyldigt PIL-billede med rigtige dimensioner."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  ndi_renderer render (skipped — Pillow mangler)")
        return

    from ndi_renderer import render_notes_frame
    img = render_notes_frame(
        current_song={"name": "Test Sang", "key": "C", "duration": "3:30",
                      "notes": "Husk at smile"},
        next_song={"name": "Næste Sang", "key": "G", "duration": "4:00", "notes": ""},
        setlist_name="MIN SETLIST",
        song_position="Sang 5 af 12",
        width=640, height=360,
    )
    assert img is not None, "render_notes_frame returnerede None"
    assert img.size == (640, 360)
    # Det skal være RGBA (vi sender det videre til NDI som BGRA)
    assert img.mode == "RGBA"
    print("  ndi_renderer renders basic frame OK")


def test_ndi_renderer_handles_no_current_song() -> None:
    """Skal kunne håndtere current_song=None uden at crashe."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  ndi_renderer no current (skipped — Pillow mangler)")
        return
    from ndi_renderer import render_notes_frame
    img = render_notes_frame(
        current_song=None, next_song=None,
        width=320, height=180,
    )
    assert img is not None
    assert img.size == (320, 180)
    print("  ndi_renderer handles None songs OK")


def test_ndi_renderer_handles_long_notes_with_wrap() -> None:
    """Lange noter skal wrappes — ikke spilde over rammen."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  ndi_renderer long notes (skipped — Pillow mangler)")
        return
    from ndi_renderer import render_notes_frame
    long_notes = " ".join(["meget lang note der skal wrappes"] * 30)
    img = render_notes_frame(
        current_song={"name": "Long", "notes": long_notes},
        next_song=None,
        width=800, height=450,
    )
    assert img is not None
    assert img.size == (800, 450)
    print("  ndi_renderer wraps long notes OK")


def test_ndi_renderer_notes_use_yellow_highlighter() -> None:
    """v1.5.4: Noter skal tegnes med GUL highlighter-baggrund (max synlighed).

    Vi tjekker at NotesColors definerer det højlighter-farveskema og at
    det er den klassiske varme gul (post-it look).
    """
    from ndi_renderer import NotesColors

    # Konstanter skal eksistere og være de korrekte gul/mørke værdier
    assert hasattr(NotesColors, "NOTES_HIGHLIGHT_BG")
    assert hasattr(NotesColors, "NOTES_HIGHLIGHT_FG")
    assert hasattr(NotesColors, "NOTES_HIGHLIGHT_BORDER")

    bg_r, bg_g, bg_b = NotesColors.NOTES_HIGHLIGHT_BG
    # Gul: høj R, høj G, lav B (yellow)
    assert bg_r > 200 and bg_g > 180 and bg_b < 120, (
        f"Forventede gul (R>200, G>180, B<120), fik RGB=({bg_r},{bg_g},{bg_b})"
    )

    fg_r, fg_g, fg_b = NotesColors.NOTES_HIGHLIGHT_FG
    # Mørk: alle kanaler skal være lave for max kontrast på gul
    assert fg_r < 60 and fg_g < 60 and fg_b < 60, (
        f"Forventede mørk forgrundsfarve, fik RGB=({fg_r},{fg_g},{fg_b})"
    )
    print("  ndi_renderer notes use yellow highlighter OK")


def test_ndi_renderer_renders_notes_box_without_crash() -> None:
    """Frame med faktiske noter skal rendere uden at fejle (regression-test
    for v1.5.4's rounded_rectangle kald)."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  ndi_renderer notes box (skipped — Pillow mangler)")
        return
    from ndi_renderer import render_notes_frame
    img = render_notes_frame(
        current_song={
            "name": "Sang med noter",
            "key": "G",
            "duration": "3:45",
            "notes": "Husk: capo på 2. bånd\nGitarsolo efter 2. omkvæd",
        },
        next_song={"name": "Næste sang", "notes": "Hurtigere tempo"},
        width=1920, height=1080,
    )
    assert img is not None
    assert img.size == (1920, 1080)
    print("  ndi_renderer renders notes box OK")


def test_stage_mode_has_yellow_highlight_colors() -> None:
    """v1.5.4: Stage Mode skal også have gul highlighter-farver til noter."""
    if not _TK_OK:
        print("  stage_mode yellow highlight (skipped — Tk not available)")
        return
    from stage_mode import StageColors

    assert hasattr(StageColors, "NOTES_HIGHLIGHT_BG")
    assert hasattr(StageColors, "NOTES_HIGHLIGHT_FG")
    assert hasattr(StageColors, "NOTES_HIGHLIGHT_BORDER")
    # Skal være hex-farver der starter med #
    assert StageColors.NOTES_HIGHLIGHT_BG.startswith("#")
    assert StageColors.NOTES_HIGHLIGHT_FG.startswith("#")
    print("  stage_mode has yellow highlight colors OK")


def test_ndi_renderer_get_current_and_next_skips_markers() -> None:
    """get_current_and_next skal springe markører over."""
    from ndi_renderer import get_current_and_next
    from setlist_model import SetlistModel, make_marker

    model = SetlistModel()
    model.add_song("Sang A")
    model.add_song("Sang B")
    model.add_song("Sang C")
    # Setliste: A, MARKER, B, C
    model.current_setlist["songs"] = ["Sang A", make_marker("PAUSE"), "Sang B", "Sang C"]

    # Start på A (index 0): next skal være B (skip marker)
    cur, nxt = get_current_and_next(model, 0)
    assert cur is not None and cur["name"] == "Sang A"
    assert nxt is not None and nxt["name"] == "Sang B"

    # Hvis vi peger på marker (index 1) skal current spring til B
    cur, nxt = get_current_and_next(model, 1)
    assert cur is not None and cur["name"] == "Sang B"
    assert nxt is not None and nxt["name"] == "Sang C"

    # På sidste sang skal next være None
    cur, nxt = get_current_and_next(model, 3)
    assert cur is not None and cur["name"] == "Sang C"
    assert nxt is None
    print("  ndi_renderer get_current_and_next skips markers OK")


def test_ndi_window_does_not_crash_when_ndi_unavailable() -> None:
    """Hvis NDI ikke er installeret skal NDINotesWindow lukke pænt med en
    fejlbesked — ikke crashe hovedappen."""
    if not _TK_OK:
        print("  ndi_window unavailable (skipped — Tk not available)")
        return

    import ndi_output
    if ndi_output.is_available():
        print("  ndi_window unavailable (skipped — NDI er faktisk installeret)")
        return

    import tkinter as tk
    from unittest.mock import patch
    from ndi_window import NDINotesWindow
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        model = SetlistModel()
        model.add_song("Test")
        model.current_setlist["songs"] = ["Test"]

        # Patch messagebox så testen ikke poppper en dialog op
        with patch("ndi_window.messagebox.showerror") as mock_err:
            win = NDINotesWindow(root, model)
            # Vinduet skal have planlagt sin egen destruction
            assert mock_err.called, "Skulle have vist 'NDI ikke tilgængelig'"
            # Lad after(10, destroy) køre
            root.update()
            root.update_idletasks()
        print("  ndi_window handles missing NDI gracefully OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


# ===========================================================================
# v1.5.3: NDIBroadcaster — headless broadcast der lever uafhængigt af UI
# ===========================================================================
def test_ndi_broadcaster_module_loads() -> None:
    """Selve modulet skal kunne importeres (det skal ikke kræve at NDI er installeret).

    Modulet importerer tkinter på top-niveau, så vi skipper hvis Tk ikke
    er tilgængeligt (matcher mønstret for de andre Tk-afhængige tests).
    """
    if not _TK_OK:
        print("  ndi_broadcaster module (skipped — Tk not available)")
        return
    import ndi_broadcaster
    assert hasattr(ndi_broadcaster, "NDIBroadcaster")
    assert hasattr(ndi_broadcaster, "MODE_NOTES")
    assert hasattr(ndi_broadcaster, "MODE_STAGE_CAPTURE")
    assert ndi_broadcaster.MODE_NOTES == "notes"
    assert ndi_broadcaster.MODE_STAGE_CAPTURE == "stage_capture"
    print("  ndi_broadcaster module loads OK")


def test_ndi_broadcaster_initial_state_is_inactive() -> None:
    """Friskt oprettet broadcaster må ikke være aktiv før start() kaldes."""
    if not _TK_OK:
        print("  ndi_broadcaster state (skipped — Tk not available)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        bc = NDIBroadcaster(root, SetlistModel())
        assert bc.is_active() is False
        assert bc.get_mode() is None
        assert bc.get_ndi_name() == ""
        assert bc.get_last_error() == ""
        assert bc.get_current_index() == 0
        assert bc.get_last_frame() is None
        print("  ndi_broadcaster initial state OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_ndi_broadcaster_start_fails_gracefully_without_ndi() -> None:
    """Hvis NDI ikke er tilgængeligt skal start() returnere False og
    sætte _last_error — ikke crashe."""
    if not _TK_OK:
        print("  ndi_broadcaster start-fail (skipped — Tk not available)")
        return

    import ndi_output
    if ndi_output.is_available():
        print("  ndi_broadcaster start-fail (skipped — NDI faktisk installeret)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster, MODE_NOTES
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        bc = NDIBroadcaster(root, SetlistModel())
        ok = bc.start(mode=MODE_NOTES, ndi_name="Test")
        assert ok is False, "start() skal returnere False når NDI mangler"
        assert bc.is_active() is False
        err = bc.get_last_error()
        assert err, "Skal have sat en hjælpsom fejlbesked"
        assert "NDI" in err
        print("  ndi_broadcaster start fails gracefully OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_ndi_broadcaster_status_listener_called_on_failed_start() -> None:
    """Status-listeners (status-indikator i topbaren) skal kaldes når
    state ændrer sig — også når start fejler."""
    if not _TK_OK:
        print("  ndi_broadcaster listener (skipped — Tk not available)")
        return

    import ndi_output
    if ndi_output.is_available():
        print("  ndi_broadcaster listener (skipped — NDI faktisk installeret)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster, MODE_NOTES
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        bc = NDIBroadcaster(root, SetlistModel())

        call_count = [0]
        def on_status():
            call_count[0] += 1

        bc.add_status_listener(on_status)
        bc.start(mode=MODE_NOTES, ndi_name="Test")  # vil fejle

        # Mindst én notify skal være sket (fra failed start)
        assert call_count[0] >= 1, (
            f"status listener skal kaldes når start fejler, "
            f"fik {call_count[0]} kald"
        )

        # Remove + verify den ikke kaldes mere
        bc.remove_status_listener(on_status)
        before = call_count[0]
        bc.stop()  # extra notify, men listener er fjernet
        assert call_count[0] == before, "fjernet listener må ikke kaldes mere"
        print("  ndi_broadcaster status listener OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_ndi_broadcaster_set_current_index_skips_markers() -> None:
    """set_current_index() skal springe over markører automatisk."""
    if not _TK_OK:
        print("  ndi_broadcaster skip-markers (skipped — Tk not available)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        model = SetlistModel()
        # Setup: sang, MARKØR, sang, sang
        model.add_song("Sang A")
        model.add_song("Sang B")
        model.add_song("Sang C")
        model.current_setlist["songs"] = [
            "Sang A",
            {"marker": "Ekstra"},
            "Sang B",
            "Sang C",
        ]
        bc = NDIBroadcaster(root, model)

        # Bedes om idx=1 (markøren) — skal hoppe til idx=2 (Sang B)
        bc.set_current_index(1)
        assert bc.get_current_index() == 2, (
            f"forventede idx=2 (Sang B), fik {bc.get_current_index()}"
        )

        # idx=0 er en sang — skal forblive 0
        bc.set_current_index(0)
        assert bc.get_current_index() == 0

        # idx=3 (Sang C) — skal forblive 3
        bc.set_current_index(3)
        assert bc.get_current_index() == 3
        print("  ndi_broadcaster set_current_index skips markers OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_ndi_broadcaster_stop_is_idempotent() -> None:
    """Det skal være sikkert at kalde stop() flere gange (selv uden start)."""
    if not _TK_OK:
        print("  ndi_broadcaster stop idempotent (skipped — Tk not available)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        bc = NDIBroadcaster(root, SetlistModel())
        # Stop uden tidligere start — skal ikke crashe
        bc.stop()
        bc.stop()
        bc.stop()
        assert bc.is_active() is False
        print("  ndi_broadcaster stop idempotent OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_ndi_broadcaster_frame_listener_can_be_removed() -> None:
    """Frame-listeners bruges af preview-vindue der lukker — vi skal kunne
    fjerne dem rent så vinduet kan lukke uden at lække."""
    if not _TK_OK:
        print("  ndi_broadcaster frame listener (skipped — Tk not available)")
        return

    import tkinter as tk
    from ndi_broadcaster import NDIBroadcaster
    from setlist_model import SetlistModel

    root = tk.Tk()
    root.withdraw()
    try:
        bc = NDIBroadcaster(root, SetlistModel())

        def on_frame(img):
            pass

        bc.add_frame_listener(on_frame)
        assert on_frame in bc._frame_listeners

        bc.remove_frame_listener(on_frame)
        assert on_frame not in bc._frame_listeners

        # remove på noget der ikke findes — skal ikke crashe
        bc.remove_frame_listener(on_frame)
        print("  ndi_broadcaster frame listener removal OK")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


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
        test_regression_notes_persist_after_edit,
        test_duplicate_setlist_basic,
        test_duplicate_setlist_is_independent,
        test_duplicate_setlist_default_name,
        test_duplicate_setlist_invalid_index,
        test_duplicate_setlist_persists_to_disk,
        test_setlist_has_modified_at_field,
        test_touch_setlist_called_on_mutations,
        test_set_active_does_NOT_touch,
        test_modified_at_persists_to_disk,
        test_modified_at_migrates_from_old_files,
        test_format_modified_at_human_readable,
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
        test_updater_installer_filename_from_url,
        test_updater_default_download_dir_creates_dir,
        test_updater_download_file_writes_atomically,
        test_updater_download_file_handles_network_error,
        test_updater_download_file_handles_ssl_error,
        test_updater_launch_installer_returns_false_when_missing,
        test_updater_launch_installer_calls_correct_command_on_unix,
        test_updater_launch_installer_silent_uses_inno_flags,
        test_version_module_has_required_fields,
        test_theme_module_loads,
        test_theme_apply_does_not_crash,
        test_stage_mode_module_loads,
        test_stage_mode_navigation_skips_markers,
        test_stage_mode_start_index_on_marker_skips_forward,
        test_stage_mode_go_to_song_number,
        test_stage_mode_supports_window_mode,
        test_stage_mode_font_scales_with_window_size,
        test_stage_mode_scroll_uses_correct_fraction_formula,
        test_hotkeys_module_loads,
        test_hotkeys_default_bindings_match_legacy,
        test_hotkeys_add_remove_reset,
        test_hotkeys_find_conflict,
        test_hotkeys_persist_to_disk_and_reload,
        test_hotkeys_load_missing_file_returns_defaults,
        test_hotkeys_load_corrupt_file_returns_defaults,
        test_hotkeys_load_filters_unknown_actions,
        test_hotkeys_format_key_human_readable,
        test_hotkeys_event_to_binding_named_keys,
        test_hotkeys_set_keys_dedupes,
        test_hotkeys_stage_mode_uses_custom_bindings,
        test_hotkeys_stage_mode_rebind_changes_live,
        test_ndi_output_module_loads,
        test_ndi_output_install_help_is_useful,
        test_ndi_output_sender_raises_clear_error_when_unavailable,
        test_ndi_renderer_module_loads,
        test_ndi_renderer_render_basic_frame,
        test_ndi_renderer_handles_no_current_song,
        test_ndi_renderer_handles_long_notes_with_wrap,
        test_ndi_renderer_notes_use_yellow_highlighter,
        test_ndi_renderer_renders_notes_box_without_crash,
        test_stage_mode_has_yellow_highlight_colors,
        test_ndi_renderer_get_current_and_next_skips_markers,
        test_ndi_window_does_not_crash_when_ndi_unavailable,
        test_ndi_broadcaster_module_loads,
        test_ndi_broadcaster_initial_state_is_inactive,
        test_ndi_broadcaster_start_fails_gracefully_without_ndi,
        test_ndi_broadcaster_status_listener_called_on_failed_start,
        test_ndi_broadcaster_set_current_index_skips_markers,
        test_ndi_broadcaster_stop_is_idempotent,
        test_ndi_broadcaster_frame_listener_can_be_removed,
    ]
    print(f"Running {len(tests)} tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed ✅")


if __name__ == "__main__":
    run_all()
