"""Renderer der laver flotte NDI-frames med sang-noter.

Bruges af "NDI Notes" mode: i stedet for at sende hele Stage Mode-vinduet,
genererer vi et purpose-built billede der KUN viser det vigtigste:
    * Nuværende sang (stor)
    * Sang-noter (mellem)
    * Næste sang + dens noter (klar til at se forude)

Det giver broadcast-software (OBS/vMix) et meget renere overlay end at
grabbe hele app-vinduet med menu-bar osv.

Bruger PIL/Pillow til al rendering — ingen Tk-afhængighed her (så vi kan
køre i baggrundstråd hvis nødvendigt).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]
    PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    PIL_AVAILABLE = False

from setlist_model import is_marker_item, item_marker_label, item_song_name, new_song


# ===========================================================================
#  Farve-tema (matcher Stage Mode for konsistent broadcast-look)
# ===========================================================================
class NotesColors:
    BG = (10, 10, 10)              # næsten sort
    BG_PANEL_NEXT = (20, 20, 22)   # lidt lysere bag næste-sang panel
    ACCENT_NOW = (0, 217, 108)     # grøn — current
    ACCENT_NEXT = (232, 158, 42)   # orange — næste

    FG_TITLE = (255, 255, 255)     # sang-titel (knaldhvid)
    FG_META = (170, 170, 175)      # toneart/varighed
    FG_NOTES = (230, 230, 235)     # noter (lys hvid) — bruges KUN som fallback
    FG_LABEL = (130, 130, 135)     # "NUVÆRENDE" / "NÆSTE" labels
    FG_MUTED = (90, 90, 95)        # mindre vigtigt

    DIVIDER = (40, 40, 45)         # tynd linje mellem paneler

    # Noter-felt — gul highlighter / post-it så de er let synlige i broadcasten
    # Matcher Stage Mode's NOTES_HIGHLIGHT_BG/FG for konsistens
    NOTES_HIGHLIGHT_BG = (253, 224, 71)     # varm gul (Tailwind yellow-300)
    NOTES_HIGHLIGHT_FG = (26, 26, 26)       # næsten sort tekst
    NOTES_HIGHLIGHT_BORDER = (202, 138, 4)  # mørkere gul kant


# ===========================================================================
#  Font-loading med fallback
# ===========================================================================
_FONT_CACHE: Dict[Tuple[str, int], object] = {}


def _find_font(weight: str = "regular") -> Optional[str]:
    """Find en pæn sans-serif font på systemet (Segoe UI / Helvetica / DejaVu)."""
    candidates_by_weight = {
        "regular": [
            # Windows
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            # macOS
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/Library/Fonts/Arial.ttf",
            # Linux
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ],
        "bold": [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ],
        "italic": [
            "C:/Windows/Fonts/segoeuii.ttf",
            "C:/Windows/Fonts/ariali.ttf",
            "/Library/Fonts/Arial Italic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        ],
    }
    for path in candidates_by_weight.get(weight, []):
        if os.path.exists(path):
            return path
    return None


def _get_font(size: int, weight: str = "regular"):
    """Cache'd font-loading. Returnerer altid en gyldig ImageFont
    (falder tilbage til default font hvis ingen system-font findes)."""
    if not PIL_AVAILABLE:
        return None
    key = (weight, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    path = _find_font(weight)
    try:
        if path:
            font = ImageFont.truetype(path, size)
        else:
            font = ImageFont.load_default()
    except (OSError, IOError):
        font = ImageFont.load_default()

    _FONT_CACHE[key] = font
    return font


# ===========================================================================
#  Tekst-wrapping helpers
# ===========================================================================
def _text_width(draw, text: str, font) -> int:
    """Mål bredde af en tekst i pixels (med fallback for ældre PIL)."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _wrap_text(draw, text: str, font, max_width: int) -> List[str]:
    """Bryd tekst i linjer der passer indenfor max_width."""
    if not text:
        return []
    lines: List[str] = []
    # Respekt eksplicitte newlines
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if _text_width(draw, test, font) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                # Ord der alene er længere end max_width: hård wrap
                if _text_width(draw, word, font) > max_width:
                    # Bryd i chunks
                    chunk = ""
                    for ch in word:
                        if _text_width(draw, chunk + ch, font) <= max_width:
                            chunk += ch
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                    current = chunk
                else:
                    current = word
        if current:
            lines.append(current)
    return lines


# ===========================================================================
#  Hovedrenderer
# ===========================================================================
def render_notes_frame(
    current_song: Optional[Dict] = None,
    next_song: Optional[Dict] = None,
    setlist_name: str = "",
    song_position: str = "",      # fx "Sang 5 af 12"
    width: int = 1920,
    height: int = 1080,
):
    """Render et NDI-egnet billede med current + næste sang.

    Returns:
        PIL.Image i RGBA mode, eller None hvis PIL ikke er installeret.

    Parameters:
        current_song: dict med 'name', 'key', 'duration', 'notes' — eller None
        next_song:    samme, eller None hvis sidste sang
        setlist_name: navn vist øverst (fx "ØVE DAG 1")
        song_position: fx "Sang 5 af 12"
        width, height: output-størrelse (typisk 1920×1080 for broadcast)
    """
    if not PIL_AVAILABLE:
        return None

    img = Image.new("RGBA", (width, height), NotesColors.BG + (255,))
    draw = ImageDraw.Draw(img)

    # === Top-bar: setliste-navn + position ===
    top_h = max(50, int(height * 0.06))
    if setlist_name or song_position:
        top_font = _get_font(max(18, int(height * 0.022)), "bold")
        # Setliste-navn (venstre)
        if setlist_name:
            draw.text(
                (int(width * 0.025), int(top_h * 0.3)),
                f"🎤  {setlist_name}",
                fill=NotesColors.FG_LABEL, font=top_font,
            )
        # Position (højre)
        if song_position:
            pos_w = _text_width(draw, song_position, top_font)
            draw.text(
                (width - int(width * 0.025) - pos_w, int(top_h * 0.3)),
                song_position,
                fill=NotesColors.FG_LABEL, font=top_font,
            )

    # Tynd divider under top-bar
    draw.line(
        [(int(width * 0.025), top_h),
         (width - int(width * 0.025), top_h)],
        fill=NotesColors.DIVIDER, width=2,
    )

    # === Hovedlayout: 2 sektioner stacked vertikalt ===
    # 60% til current, 40% til next (current er det vigtigste)
    content_y = top_h + int(height * 0.025)
    available_h = height - content_y - int(height * 0.02)
    current_h = int(available_h * 0.58)
    next_h = available_h - current_h - int(height * 0.02)

    pad_x = int(width * 0.04)
    inner_w = width - 2 * pad_x

    # === SEKTION 1: NUVÆRENDE SANG ===
    _draw_song_section(
        draw, img,
        x=pad_x, y=content_y,
        w=inner_w, h=current_h,
        label="▶  NUVÆRENDE",
        accent=NotesColors.ACCENT_NOW,
        song=current_song,
        is_current=True,
        height_ref=height,
        bg_color=NotesColors.BG,
    )

    # === SEKTION 2: NÆSTE SANG ===
    next_y = content_y + current_h + int(height * 0.02)
    _draw_song_section(
        draw, img,
        x=pad_x, y=next_y,
        w=inner_w, h=next_h,
        label="⏭  NÆSTE SANG",
        accent=NotesColors.ACCENT_NEXT,
        song=next_song,
        is_current=False,
        height_ref=height,
        bg_color=NotesColors.BG_PANEL_NEXT,
    )

    return img


def _draw_song_section(
    draw, img,
    *,
    x: int, y: int, w: int, h: int,
    label: str,
    accent: Tuple[int, int, int],
    song: Optional[Dict],
    is_current: bool,
    height_ref: int,
    bg_color: Tuple[int, int, int],
) -> None:
    """Tegn én sang-sektion (current eller next) inde i et "panel"."""
    # Panel-baggrund
    panel = Image.new("RGBA", (w, h), bg_color + (255,))
    img.paste(panel, (x, y))

    # Venstre accent-stribe (paste én farve-blok — meget hurtigere end putpixel)
    stripe_w = max(4, int(height_ref * 0.005))
    stripe = Image.new("RGBA", (stripe_w, h), accent + (255,))
    img.paste(stripe, (x, y))

    # Inde-padding
    width_pad = int(height_ref * 0.018)
    inner_x = x + stripe_w + width_pad
    inner_y = y + int(height_ref * 0.015)
    inner_w = w - stripe_w - 2 * width_pad

    # Label ("▶ NUVÆRENDE" eller "⏭ NÆSTE SANG")
    label_size = max(14, int(height_ref * (0.018 if is_current else 0.016)))
    label_font = _get_font(label_size, "bold")
    draw.text(
        (inner_x, inner_y), label,
        fill=accent, font=label_font,
    )

    cursor_y = inner_y + label_size + int(height_ref * 0.012)

    # Hvis ingen sang (sidste sang ramte næste = None)
    if song is None:
        empty_size = max(20, int(height_ref * (0.035 if is_current else 0.028)))
        empty_font = _get_font(empty_size, "italic")
        empty_msg = "— Slut på sætlisten —" if not is_current else "— Ingen sang valgt —"
        draw.text(
            (inner_x, cursor_y), empty_msg,
            fill=NotesColors.FG_MUTED, font=empty_font,
        )
        return

    # Sangens navn (KÆMPE for current, mellem for next)
    name = song.get("name", "")
    name_size = max(28, int(height_ref * (0.075 if is_current else 0.045)))
    name_font = _get_font(name_size, "bold")
    # Wrap hvis navnet er meget langt
    name_lines = _wrap_text(draw, name, name_font, inner_w)
    for line in name_lines[:2]:  # max 2 linjer (ellers spises hele sektionen)
        draw.text(
            (inner_x, cursor_y), line,
            fill=NotesColors.FG_TITLE, font=name_font,
        )
        cursor_y += int(name_size * 1.1)

    # Meta: toneart · varighed
    extras = [v for v in (song.get("key", ""), song.get("duration", "")) if v]
    if extras:
        meta_size = max(14, int(height_ref * (0.025 if is_current else 0.02)))
        meta_font = _get_font(meta_size)
        meta_text = "   ·   ".join(extras)
        draw.text(
            (inner_x, cursor_y + int(height_ref * 0.005)), meta_text,
            fill=NotesColors.FG_META, font=meta_font,
        )
        cursor_y += meta_size + int(height_ref * 0.018)
    else:
        cursor_y += int(height_ref * 0.01)

    # Noter (multi-line med wrap) — GUL HIGHLIGHTER så de er let synlige
    notes = (song.get("notes") or "").strip()
    if notes:
        notes_size = max(16, int(height_ref * (0.028 if is_current else 0.022)))
        notes_font = _get_font(notes_size)
        notes_lines = _wrap_text(draw, notes, notes_font, inner_w - int(height_ref * 0.025))
        # Hvor mange linjer er der plads til?
        remaining_h = (y + h) - cursor_y - int(height_ref * 0.015)
        line_h = int(notes_size * 1.35)
        # Plads til highlighter-padding + evt. truncation indikator
        pad_v = int(notes_size * 0.4)
        max_lines = max(1, (remaining_h - 2 * pad_v) // line_h)
        visible_lines = notes_lines[:max_lines]
        truncated = len(notes_lines) > max_lines

        # === Gul højlighter-boks bag noterne ===
        if visible_lines:
            box_h = line_h * len(visible_lines) + 2 * pad_v
            pad_h = int(height_ref * 0.012)
            box_x0 = inner_x - pad_h
            box_y0 = cursor_y - pad_v
            box_x1 = inner_x + inner_w
            box_y1 = box_y0 + box_h

            # Fyld + kant — gul highlighter look
            try:
                draw.rounded_rectangle(
                    [box_x0, box_y0, box_x1, box_y1],
                    radius=max(4, int(height_ref * 0.008)),
                    fill=NotesColors.NOTES_HIGHLIGHT_BG,
                    outline=NotesColors.NOTES_HIGHLIGHT_BORDER,
                    width=max(2, int(height_ref * 0.003)),
                )
            except AttributeError:
                # PIL < 8.2 har ikke rounded_rectangle — fald tilbage
                draw.rectangle(
                    [box_x0, box_y0, box_x1, box_y1],
                    fill=NotesColors.NOTES_HIGHLIGHT_BG,
                    outline=NotesColors.NOTES_HIGHLIGHT_BORDER,
                    width=max(2, int(height_ref * 0.003)),
                )

            # Mørk tekst oven på den gule baggrund
            for line in visible_lines:
                draw.text(
                    (inner_x, cursor_y), line,
                    fill=NotesColors.NOTES_HIGHLIGHT_FG, font=notes_font,
                )
                cursor_y += line_h

            # "..." hvis vi måtte trunkere
            if truncated:
                draw.text(
                    (inner_x, cursor_y - line_h + int(line_h * 0.5)),
                    "...",
                    fill=NotesColors.NOTES_HIGHLIGHT_FG, font=notes_font,
                )
    else:
        # Ingen noter — vis bare en lille placeholder (samme som før)
        ph_size = max(14, int(height_ref * 0.02))
        ph_font = _get_font(ph_size, "italic")
        draw.text(
            (inner_x, cursor_y), "(ingen noter til denne sang)",
            fill=NotesColors.FG_MUTED, font=ph_font,
        )


# ===========================================================================
#  Convenience: hent current + next fra en SetlistModel
# ===========================================================================
def get_current_and_next(model, current_idx: int) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Slå current + næste sang op i modellen (spring markører over).

    Returns (current_song_dict_or_None, next_song_dict_or_None)
    """
    items = model.current_setlist.get("songs", [])
    if not items or current_idx < 0 or current_idx >= len(items):
        return (None, None)

    # Current — spring frem hvis markør
    cur_idx = current_idx
    while cur_idx < len(items) and is_marker_item(items[cur_idx]):
        cur_idx += 1
    current = None
    if cur_idx < len(items):
        cur_name = item_song_name(items[cur_idx])
        current = model.get_song(cur_name) or new_song(cur_name)

    # Next — første ikke-markør sang efter current
    nxt_idx = cur_idx + 1
    while nxt_idx < len(items) and is_marker_item(items[nxt_idx]):
        nxt_idx += 1
    nxt = None
    if nxt_idx < len(items):
        nxt_name = item_song_name(items[nxt_idx])
        nxt = model.get_song(nxt_name) or new_song(nxt_name)

    return (current, nxt)
