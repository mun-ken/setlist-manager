"""Web-server der streamer setlisten live til browsere på samme netværk.

Bandet kan åbne en URL på deres telefon/iPad og se setlisten — den
opdaterer sig automatisk når master-PC'en skifter sang.

Arkitektur:
-----------
* http.server i en background thread (Python's stdlib — ingen deps)
* Server-Sent Events (SSE) til live updates — browser auto-reconnects
* Listener-pattern: appen kalder set_current_index() / set_model() når
  noget ændrer sig, og alle åbne browsere får besked

URLs:
  /              → forside (vælg visning)
  /setlist       → ren setliste uden noter
  /notes         → setliste med noter (samme indhold som NDI)
  /events        → SSE-stream af live-updates
  /api/state     → JSON snapshot (debug + initial load)

Sikkerhed:
* Binder kun på 0.0.0.0:8765 (lokal port) — kun samme netværk
* INGEN write-endpoints — kun læse-adgang
* Ingen authentication (read-only på lokalnet vurderet OK for bandet)
"""

from __future__ import annotations

import html
import json
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional
from urllib.parse import urlparse

from setlist_model import (
    SetlistModel,
    is_marker_item,
    item_marker_label,
    item_song_name,
)


DEFAULT_PORT = 8765


# ===========================================================================
#  Snapshot — alt en klient behøver for at vise current state
# ===========================================================================
def build_state_snapshot(
    model: SetlistModel,
    current_idx: int,
) -> dict:
    """Lav et JSON-venligt snapshot af den nuværende setliste + position."""
    items = model.current_setlist.get("songs", [])
    band_name = ""
    if model.current_band:
        band_name = model.current_band.get("name", "")
    setlist_name = model.current_setlist.get("name", "")

    # Beregn 1-baseret sang-nummer (uden markører)
    songs_list = []
    song_num = 0
    current_song_num = 0  # 1-baseret nummer på current
    for idx, item in enumerate(items):
        if is_marker_item(item):
            songs_list.append({
                "idx": idx,
                "type": "marker",
                "label": item_marker_label(item),
            })
        else:
            song_num += 1
            name = item_song_name(item)
            song = model.get_song(name) or {}
            is_current = (idx == current_idx)
            if is_current:
                current_song_num = song_num
            songs_list.append({
                "idx": idx,
                "type": "song",
                "num": song_num,
                "name": name,
                "key": song.get("key", ""),
                "duration": song.get("duration", ""),
                "notes": song.get("notes", ""),
                "is_current": is_current,
            })

    # Find current + next song (spring markører over) — bruges af /notes view
    current_song = None
    next_song = None
    for s in songs_list:
        if s["type"] != "song":
            continue
        if current_song is None and s["is_current"]:
            current_song = s
        elif current_song is not None:
            next_song = s
            break

    return {
        "band": band_name,
        "setlist": setlist_name,
        "current_idx": current_idx,
        "current_num": current_song_num,
        "songs": songs_list,
        "total_songs": song_num,
        "current_song": current_song,
        "next_song": next_song,
    }


# ===========================================================================
#  SSE Event Broker — holder styr på alle åbne browser-connections
# ===========================================================================
class _EventBroker:
    """Tråd-sikker broker der pusher events til alle aktive SSE-clients."""

    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """En ny klient connecter — giv den en kø den kan læse fra."""
        q: queue.Queue = queue.Queue(maxsize=20)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event_data: str) -> None:
        """Push et event til alle aktive klienter (drop hvis køen er fuld)."""
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    # Klienten er langsom — drop denne event for dem
                    pass

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)


# ===========================================================================
#  HTML-templates (server-rendered — ingen JS-framework)
# ===========================================================================
_INDEX_HTML = """<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Setlist Manager</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #0a0a0a; color: #e5e5ea;
    min-height: 100vh;
  }
  .wrap {
    max-width: 480px; margin: 0 auto;
    padding: 32px 20px;
    min-height: 100vh;
    display: flex; flex-direction: column;
    justify-content: center;
  }
  h1 {
    font-size: 28px; margin: 0 0 6px 0; text-align: center;
    font-weight: 700;
  }
  .subtitle {
    text-align: center; color: #8e8e93;
    font-size: 15px; margin-bottom: 36px;
  }
  .band, .setlist {
    text-align: center; color: #aeaeb2;
  }
  .band { font-size: 14px; margin-bottom: 4px; }
  .setlist { font-size: 17px; font-weight: 600; color: #e5e5ea; }
  .choice-grid { display: grid; gap: 14px; margin-top: 32px; }
  .choice {
    display: block; text-decoration: none;
    padding: 24px 20px;
    border-radius: 14px;
    background: #1c1c1e;
    border: 2px solid #2c2c2e;
    color: #e5e5ea;
    transition: all 0.15s;
    -webkit-tap-highlight-color: transparent;
  }
  .choice:active { transform: scale(0.98); }
  .choice:hover { border-color: #00d96c; background: #1f1f22; }
  .choice .icon { font-size: 36px; margin-bottom: 8px; display: block; }
  .choice .title { font-size: 19px; font-weight: 600; margin-bottom: 4px; }
  .choice .desc { font-size: 13px; color: #8e8e93; }
  .footer {
    text-align: center; color: #48484a;
    font-size: 12px; margin-top: 40px;
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>🎸 Setlist Manager</h1>
  <div class="subtitle">Vælg visning</div>

  <div class="band">{{band}}</div>
  <div class="setlist">{{setlist}}</div>

  <div class="choice-grid">
    <a class="choice" href="/setlist">
      <span class="icon">📋</span>
      <div class="title">Kun setliste</div>
      <div class="desc">Rene sangtitler uden noter — godt overblik</div>
    </a>
    <a class="choice" href="/notes">
      <span class="icon">📝</span>
      <div class="title">Setliste med noter</div>
      <div class="desc">Samme som NDI-broadcast — sang + noter</div>
    </a>
  </div>

  <div class="footer">Opdateres live når master-PC skifter sang</div>
</div>
</body>
</html>
"""


_SETLIST_HTML = """<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Setlist — {{setlist}}</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #0a0a0a; color: #e5e5ea;
    min-height: 100vh;
  }
  .header {
    position: sticky; top: 0;
    background: #0a0a0a;
    padding: 14px 20px 12px;
    border-bottom: 1px solid #1c1c1e;
    z-index: 10;
  }
  .header .band { font-size: 12px; color: #8e8e93; }
  .header .title {
    font-size: 18px; font-weight: 700;
    display: flex; align-items: center; gap: 10px;
  }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #00d96c;
    animation: pulse 1.8s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.85); }
  }
  .home-link {
    float: right; color: #8e8e93; font-size: 13px;
    text-decoration: none; padding: 4px 8px;
    border: 1px solid #2c2c2e; border-radius: 6px;
  }
  ul { list-style: none; margin: 0; padding: 8px 0 60px 0; }
  li {
    padding: 14px 20px;
    border-bottom: 1px solid #1c1c1e;
    display: flex; align-items: center; gap: 14px;
    transition: background 0.2s;
  }
  li.current {
    background: linear-gradient(90deg, rgba(0,217,108,0.15), rgba(0,217,108,0.02));
    border-left: 4px solid #00d96c;
    padding-left: 16px;
  }
  li.past { opacity: 0.35; }
  li.marker {
    background: rgba(232,158,42,0.08);
    color: #e89e2a;
    font-weight: 600;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    justify-content: center;
  }
  .num {
    color: #6e6e73; font-variant-numeric: tabular-nums;
    min-width: 26px; font-size: 14px;
  }
  li.current .num { color: #00d96c; font-weight: 700; }
  .name { flex: 1; font-size: 17px; }
  li.current .name { font-weight: 700; font-size: 18px; }
  .meta {
    color: #8e8e93; font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  .notes-block {
    background: #fde047; color: #1a1a1a;
    border-radius: 10px; padding: 14px 16px; margin-top: 10px;
    font-size: 15px; line-height: 1.4;
    white-space: pre-wrap;
    border-left: 4px solid #ca8a04;
  }
  .empty-notes {
    color: #48484a; font-style: italic; font-size: 13px; margin-top: 6px;
  }
  .reconnecting {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #d70015; color: #fff;
    padding: 8px 16px; border-radius: 20px;
    font-size: 13px; opacity: 0;
    transition: opacity 0.3s;
  }
  .reconnecting.show { opacity: 1; }
</style>
</head>
<body>
<div class="header">
  <a class="home-link" href="/">← Skift visning</a>
  <div class="band">{{band}}</div>
  <div class="title">
    <span class="live-dot"></span>
    {{setlist}}
  </div>
</div>
<ul id="list">
{{rows}}
</ul>
<div class="reconnecting" id="reconnect">Genopretter forbindelse…</div>
<script>
(function() {
  const VIEW = "{{view}}";  // "setlist" eller "notes"
  let evt = null;
  const reconnectEl = document.getElementById("reconnect");

  function render(state) {
    const ul = document.getElementById("list");
    if (!ul) return;
    let html = "";
    let pastSection = true;  // alle items før current er "past"
    for (const item of state.songs) {
      if (item.idx === state.current_idx) pastSection = false;
      if (item.type === "marker") {
        html += `<li class="marker">${escapeHtml(item.label)}</li>`;
      } else {
        const cls = (item.idx === state.current_idx) ? "current"
                  : (pastSection ? "past" : "");
        const meta = [item.key, item.duration].filter(Boolean).join(" · ");
        let notesHtml = "";
        if (VIEW === "notes") {
          if (item.notes && item.notes.trim()) {
            notesHtml = `<div style="flex-basis:100%"><div class="notes-block">📝 ${escapeHtml(item.notes)}</div></div>`;
          } else if (item.idx === state.current_idx) {
            notesHtml = `<div style="flex-basis:100%"><div class="empty-notes">(ingen noter)</div></div>`;
          }
        }
        html += `<li class="${cls}" style="flex-wrap:wrap">
          <span class="num">${item.num}.</span>
          <span class="name">${escapeHtml(item.name)}</span>
          ${meta ? `<span class="meta">${escapeHtml(meta)}</span>` : ""}
          ${notesHtml}
        </li>`;
      }
    }
    ul.innerHTML = html;

    // Scroll til current
    const cur = ul.querySelector("li.current");
    if (cur) {
      const rect = cur.getBoundingClientRect();
      const headerH = document.querySelector(".header").offsetHeight;
      if (rect.top < headerH + 20 || rect.bottom > window.innerHeight - 40) {
        cur.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"
    })[c]);
  }

  function connect() {
    if (evt) evt.close();
    evt = new EventSource("/events");
    evt.onopen = () => { reconnectEl.classList.remove("show"); };
    evt.onmessage = (e) => {
      try { render(JSON.parse(e.data)); }
      catch (err) { console.error(err); }
    };
    evt.onerror = () => {
      reconnectEl.classList.add("show");
      // EventSource genopretter automatisk — vi viser bare statusen
    };
  }
  connect();
})();
</script>
</body>
</html>
"""


# ===========================================================================
#  /notes view — store kort med NUVÆRENDE + NÆSTE SANG (ligesom NDI preview)
# ===========================================================================
_NOTES_HTML = """<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{{setlist}} — Noter</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #0a0a0a; color: #e5e5ea;
    min-height: 100vh;
  }
  .header {
    position: sticky; top: 0;
    background: rgba(10,10,10,0.95);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    padding: 10px 16px;
    border-bottom: 1px solid #1c1c1e;
    z-index: 10;
    display: flex; align-items: center; justify-content: space-between;
    font-size: 13px;
  }
  .header .left { display: flex; align-items: center; gap: 8px; color: #aeaeb2; }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #00d96c;
    animation: pulse 1.8s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.85); }
  }
  .header .position { color: #e5e5ea; font-weight: 600; }
  .home-link {
    color: #8e8e93; text-decoration: none;
    padding: 4px 10px;
    border: 1px solid #2c2c2e; border-radius: 6px;
  }
  .main { padding: 16px; max-width: 900px; margin: 0 auto; }

  /* Sang-kort — matcher NDI renderer farver */
  .card {
    background: #141417;
    border-radius: 14px;
    padding: 22px 22px 26px 26px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
  }
  .card.next { background: #131316; }
  /* Venstre accent-stribe */
  .card::before {
    content: ""; position: absolute;
    left: 0; top: 0; bottom: 0; width: 5px;
  }
  .card.current::before { background: #00d96c; }
  .card.next::before { background: #e89e2a; }

  .card .label {
    font-size: 12px; font-weight: 700;
    letter-spacing: 1.5px; text-transform: uppercase;
    margin-bottom: 10px;
  }
  .card.current .label { color: #00d96c; }
  .card.next .label { color: #e89e2a; }

  .card .name {
    font-size: 32px; line-height: 1.1;
    font-weight: 800;
    color: #fff;
    margin-bottom: 8px;
    word-break: break-word;
  }
  .card.next .name { font-size: 24px; }

  .card .meta {
    color: #aeaeb2;
    font-size: 15px;
    font-variant-numeric: tabular-nums;
    margin-bottom: 14px;
  }
  .card.next .meta { font-size: 13px; }

  /* Noter — gul highlighter ligesom Stage Mode + NDI */
  .notes-box {
    background: #fde047;
    color: #1a1a1a;
    border-left: 5px solid #ca8a04;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 16px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .card.next .notes-box { font-size: 14px; padding: 10px 14px; }
  .notes-box .icon { font-size: 17px; margin-right: 4px; }

  .empty-notes {
    color: #48484a; font-style: italic; font-size: 14px;
  }

  .end-of-set {
    text-align: center;
    color: #6e6e73;
    padding: 24px;
    font-style: italic;
    font-size: 16px;
  }

  .reconnecting {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #d70015; color: #fff;
    padding: 8px 16px; border-radius: 20px;
    font-size: 13px; opacity: 0;
    transition: opacity 0.3s;
  }
  .reconnecting.show { opacity: 1; }

  /* Bigger fonts on tablets */
  @media (min-width: 768px) {
    .card { padding: 28px 28px 32px 32px; }
    .card .name { font-size: 44px; }
    .card.next .name { font-size: 32px; }
    .notes-box { font-size: 19px; }
    .card.next .notes-box { font-size: 16px; }
  }
</style>
</head>
<body>
<div class="header">
  <div class="left">
    <span class="live-dot"></span>
    <span>{{setlist}}</span>
  </div>
  <div class="position" id="position">{{position}}</div>
  <a class="home-link" href="/">← Skift</a>
</div>
<div class="main" id="main">
  <div id="current-slot">{{current_card}}</div>
  <div id="next-slot">{{next_card}}</div>
</div>
<div class="reconnecting" id="reconnect">Genopretter forbindelse…</div>
<script>
(function() {
  let evt = null;
  const reconnectEl = document.getElementById("reconnect");
  const positionEl = document.getElementById("position");
  const currentSlot = document.getElementById("current-slot");
  const nextSlot = document.getElementById("next-slot");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"
    })[c]);
  }

  function renderSongCard(song, isCurrent) {
    if (!song) {
      if (isCurrent) {
        return `<div class="end-of-set">— Ingen sang valgt —</div>`;
      }
      return `<div class="end-of-set">— Slut på sætlisten —</div>`;
    }
    const cls = isCurrent ? "card current" : "card next";
    const label = isCurrent ? "▶ Nuværende" : "⏭ Næste sang";
    const meta = [song.key, song.duration].filter(Boolean).join("   ·   ");
    const notes = (song.notes || "").trim();
    let notesHtml = "";
    if (notes) {
      notesHtml = `<div class="notes-box"><span class="icon">📝</span>${escapeHtml(notes)}</div>`;
    } else if (isCurrent) {
      notesHtml = `<div class="empty-notes">(ingen noter til denne sang)</div>`;
    }
    return `
      <div class="${cls}">
        <div class="label">${label}</div>
        <div class="name">${escapeHtml(song.name)}</div>
        ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}
        ${notesHtml}
      </div>`;
  }

  function render(state) {
    // Position-tekst (fx "Sang 6 af 19")
    if (state.current_num && state.total_songs) {
      positionEl.textContent = `Sang ${state.current_num} af ${state.total_songs}`;
    } else {
      positionEl.textContent = "";
    }
    currentSlot.innerHTML = renderSongCard(state.current_song, true);
    nextSlot.innerHTML = renderSongCard(state.next_song, false);
  }

  function connect() {
    if (evt) evt.close();
    evt = new EventSource("/events");
    evt.onopen = () => { reconnectEl.classList.remove("show"); };
    evt.onmessage = (e) => {
      try { render(JSON.parse(e.data)); }
      catch (err) { console.error(err); }
    };
    evt.onerror = () => {
      reconnectEl.classList.add("show");
    };
  }
  connect();
})();
</script>
</body>
</html>
"""


def _render_position_text(state: dict) -> str:
    """Format 'Sang X af Y' header text."""
    if state.get("current_num") and state.get("total_songs"):
        return f'Sang {state["current_num"]} af {state["total_songs"]}'
    return ""


def _render_song_card(song: Optional[dict], *, is_current: bool) -> str:
    """Server-render et sang-kort (så side virker uden JS også)."""
    if song is None:
        if is_current:
            return '<div class="end-of-set">— Ingen sang valgt —</div>'
        return '<div class="end-of-set">— Slut på sætlisten —</div>'

    cls = "card current" if is_current else "card next"
    label = "▶ Nuværende" if is_current else "⏭ Næste sang"
    meta_parts = [v for v in (song.get("key", ""), song.get("duration", "")) if v]
    meta = "   ·   ".join(meta_parts)
    meta_html = f'<div class="meta">{html.escape(meta)}</div>' if meta else ""

    notes = (song.get("notes") or "").strip()
    if notes:
        notes_html = (
            f'<div class="notes-box"><span class="icon">📝</span>'
            f'{html.escape(notes)}</div>'
        )
    elif is_current:
        notes_html = '<div class="empty-notes">(ingen noter til denne sang)</div>'
    else:
        notes_html = ""

    return (
        f'<div class="{cls}">'
        f'<div class="label">{label}</div>'
        f'<div class="name">{html.escape(song["name"])}</div>'
        f'{meta_html}{notes_html}'
        f'</div>'
    )


def _render_initial_rows(state: dict, view: str) -> str:
    """Server-side render af første HTML — så siden virker også uden JS."""
    rows = []
    pre_current = True
    for item in state["songs"]:
        if item["idx"] == state["current_idx"]:
            pre_current = False
        if item["type"] == "marker":
            rows.append(
                f'<li class="marker">{html.escape(item["label"])}</li>'
            )
        else:
            cls_parts = []
            if item["idx"] == state["current_idx"]:
                cls_parts.append("current")
            elif pre_current:
                cls_parts.append("past")
            cls = " ".join(cls_parts)
            meta = " · ".join(
                v for v in (item["key"], item["duration"]) if v
            )
            meta_html = (
                f'<span class="meta">{html.escape(meta)}</span>' if meta else ""
            )
            notes_html = ""
            if view == "notes":
                notes = item.get("notes", "").strip()
                if notes:
                    notes_html = (
                        '<div style="flex-basis:100%">'
                        '<div class="notes-block">📝 '
                        f'{html.escape(notes)}</div></div>'
                    )
                elif item["idx"] == state["current_idx"]:
                    notes_html = (
                        '<div style="flex-basis:100%">'
                        '<div class="empty-notes">(ingen noter)</div></div>'
                    )
            rows.append(
                f'<li class="{cls}" style="flex-wrap:wrap">'
                f'<span class="num">{item["num"]}.</span>'
                f'<span class="name">{html.escape(item["name"])}</span>'
                f'{meta_html}{notes_html}</li>'
            )
    return "\n".join(rows)


# ===========================================================================
#  HTTP request handler
# ===========================================================================
class _RequestHandler(BaseHTTPRequestHandler):
    # Disse settes af WebServer før den starter
    server_app: "WebServer" = None  # type: ignore[assignment]

    # Dæmp console-spam — vi vil ikke se HTTP-log i terminalen
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._render_index()
            elif path == "/setlist":
                self._render_list_page("setlist")
            elif path == "/notes":
                self._render_notes_page()
            elif path == "/events":
                self._stream_events()
            elif path == "/api/state":
                self._render_state_json()
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            # Klient lukkede forbindelsen — helt normalt, ignorér
            pass

    # --- pages ----------------------------------------------------------
    def _render_index(self):
        state = self.server_app._snapshot()
        body = _INDEX_HTML.replace(
            "{{band}}", html.escape(state["band"] or "(intet band)")
        ).replace(
            "{{setlist}}", html.escape(state["setlist"] or "(ingen setliste)")
        )
        self._send_html(body)

    def _render_list_page(self, view: str):
        state = self.server_app._snapshot()
        body = _SETLIST_HTML.replace(
            "{{band}}", html.escape(state["band"] or "—")
        ).replace(
            "{{setlist}}", html.escape(state["setlist"] or "Setlist")
        ).replace(
            "{{view}}", view
        ).replace(
            "{{rows}}", _render_initial_rows(state, view)
        )
        self._send_html(body)

    def _render_notes_page(self):
        """Render NDI-preview-style notes view (current + next song cards)."""
        state = self.server_app._snapshot()
        body = (
            _NOTES_HTML
            .replace("{{setlist}}", html.escape(state.get("setlist") or "Setlist"))
            .replace("{{position}}", _render_position_text(state))
            .replace("{{current_card}}", _render_song_card(
                state.get("current_song"), is_current=True))
            .replace("{{next_card}}", _render_song_card(
                state.get("next_song"), is_current=False))
        )
        self._send_html(body)

    def _render_state_json(self):
        state = self.server_app._snapshot()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(state).encode("utf-8"))

    # --- SSE-stream ------------------------------------------------------
    def _stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")  # disable nginx buffering
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Send initial state straks
        state = self.server_app._snapshot()
        self._send_sse(json.dumps(state))

        # Subscribe på broker'en
        q = self.server_app._broker.subscribe()
        try:
            while not self.server_app._stop_flag.is_set():
                try:
                    data = q.get(timeout=15.0)
                    self._send_sse(data)
                except queue.Empty:
                    # Heartbeat så proxies ikke lukker forbindelsen
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        finally:
            self.server_app._broker.unsubscribe(q)

    def _send_sse(self, data: str):
        try:
            payload = f"data: {data}\n\n".encode("utf-8")
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise  # bobler op til finally så vi unsubscriber

    # --- helper ----------------------------------------------------------
    def _send_html(self, body: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ===========================================================================
#  WebServer — facade brugt af main app
# ===========================================================================
class WebServer:
    """HTTP-server der streamer setlisten live til browsere.

    Lifecycle:
        ws = WebServer(model)
        ws.start()
        ws.set_current_index(5)  # når brugeren skifter sang
        # ... på app-luk:
        ws.stop()
    """

    def __init__(
        self,
        model: SetlistModel,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.model = model
        self.port = port
        self._current_idx: int = 0
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._broker = _EventBroker()
        self._stop_flag = threading.Event()
        self._actual_port: Optional[int] = None

        # Status-listeners (kaldes ved start/stop) — bruges af topbar-indikator
        self._status_listeners: List[Callable[[], None]] = []

    # ------------------------------------------------------------------
    def add_status_listener(self, cb: Callable[[], None]) -> None:
        if cb not in self._status_listeners:
            self._status_listeners.append(cb)

    def remove_status_listener(self, cb: Callable[[], None]) -> None:
        if cb in self._status_listeners:
            self._status_listeners.remove(cb)

    def _notify_status(self) -> None:
        for cb in list(self._status_listeners):
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                print(f"[WebServer] status listener fejl: {e}")

    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    def get_port(self) -> Optional[int]:
        return self._actual_port if self.is_running() else None

    def get_urls(self) -> List[str]:
        """Returnér URL'er bandet kan tilgå (loopback + LAN-IP'er)."""
        if not self.is_running():
            return []
        port = self._actual_port
        urls = [f"http://localhost:{port}"]
        # Find lokale IP-adresser så bandet kan tilgå fra deres telefon
        try:
            hostname = socket.gethostname()
            # Forsøg at finde primær LAN-IP (UDP-trick — sender ingen pakker)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
            if lan_ip and not lan_ip.startswith("127."):
                urls.append(f"http://{lan_ip}:{port}")
        except OSError:
            pass
        return urls

    def get_client_count(self) -> int:
        return self._broker.client_count()

    # ------------------------------------------------------------------
    def set_current_index(self, idx: int) -> None:
        """Kaldes af appen når brugeren skifter sang — pusher til klienter."""
        items = self.model.current_setlist.get("songs", [])
        if not items:
            return
        # Clamp og hop frem hvis markør
        idx = max(0, min(idx, len(items) - 1))
        while idx < len(items) and is_marker_item(items[idx]):
            idx += 1
        if idx >= len(items):
            return
        if idx != self._current_idx:
            self._current_idx = idx
        self._broadcast_state()

    def notify_model_changed(self) -> None:
        """Kaldes når setlisten selv er ændret (ny sang tilføjet, etc.)."""
        self._broadcast_state()

    def _broadcast_state(self) -> None:
        if self.is_running():
            state = build_state_snapshot(self.model, self._current_idx)
            self._broker.publish(json.dumps(state))

    def _snapshot(self) -> dict:
        return build_state_snapshot(self.model, self._current_idx)

    # ------------------------------------------------------------------
    def start(self) -> bool:
        """Start serveren. Returnerer True hvis det lykkedes."""
        if self.is_running():
            return True
        self._stop_flag.clear()

        # Lav handler-klasse med reference til os selv
        server_app_ref = self
        class _Handler(_RequestHandler):
            server_app = server_app_ref  # type: ignore[assignment]

        # Prøv den ønskede port først — hvis taget, prøv et par stykker mere
        last_err = None
        for try_port in [self.port, self.port + 1, self.port + 2, 0]:
            try:
                self._httpd = ThreadingHTTPServer(("0.0.0.0", try_port), _Handler)
                self._actual_port = self._httpd.server_address[1]
                break
            except OSError as e:
                last_err = e
                continue

        if self._httpd is None:
            print(f"[WebServer] Kunne ikke binde til port: {last_err}")
            self._notify_status()
            return False

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="WebServer",
            daemon=True,
        )
        self._thread.start()
        self._notify_status()
        return True

    def stop(self) -> None:
        """Stop serveren pænt."""
        self._stop_flag.set()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception as e:  # noqa: BLE001
                print(f"[WebServer] stop fejl: {e}")
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._actual_port = None
        self._notify_status()
