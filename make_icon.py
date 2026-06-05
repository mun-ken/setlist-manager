"""Generate assets/app.ico — a simple Setlist Manager icon.

Run as part of the build, before PyInstaller.
If Pillow isn't installed the script exits silently so the build can
continue without an icon.
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    out = Path(__file__).parent / "assets" / "app.ico"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed - skipping icon generation.")
        return 0

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background disc (deep blue)
    margin = 6
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        fill=(30, 60, 130, 255),
    )
    # Subtle inner ring
    draw.ellipse(
        (margin + 14, margin + 14, size - margin - 14, size - margin - 14),
        outline=(255, 255, 255, 70),
        width=3,
    )

    # Eighth-note glyph
    head_w, head_h = 72, 54
    head_x, head_y = 64, 148
    # note head (slightly tilted oval approximated by an ellipse)
    draw.ellipse(
        (head_x, head_y, head_x + head_w, head_y + head_h),
        fill=(255, 255, 255, 255),
    )
    # stem
    stem_x = head_x + head_w - 8
    draw.rectangle(
        (stem_x, 54, stem_x + 8, head_y + head_h // 2),
        fill=(255, 255, 255, 255),
    )
    # flag
    draw.polygon(
        [
            (stem_x + 8, 54),
            (stem_x + 70, 88),
            (stem_x + 64, 138),
            (stem_x + 8, 108),
        ],
        fill=(255, 255, 255, 255),
    )

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(out, format="ICO", sizes=sizes)
    print(f"Wrote {out}  ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
