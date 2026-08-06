"""Generate the application icons Tauri needs for bundling.

Written with the standard library alone. The alternative was adding an imaging dependency to
produce four small files, or committing binaries nobody can regenerate or review. This way the
mark is defined in code: change the constants below and rerun.

    uv run python scripts/generate_icons.py

The design is a rounded square in the interface's accent colour carrying a five-bar waveform,
which reads at 32 pixels where a microphone silhouette would turn to mush. Everything is drawn
at four times the target size and averaged down, which is where the smooth edges come from.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

Colour = tuple[int, int, int, int]
Pixels = list[list[Colour]]

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "desktop" / "icons"

BACKGROUND: Colour = (13, 148, 156, 255)
FOREGROUND: Colour = (240, 253, 255, 255)
TRANSPARENT: Colour = (0, 0, 0, 0)

SUPERSAMPLE = 4
CORNER_RADIUS_RATIO = 0.22

# Relative bar heights, centre outwards. Uneven on purpose: a symmetric block reads as a
# barcode rather than as sound.
BAR_HEIGHTS = (0.34, 0.62, 1.0, 0.72, 0.44)
BAR_WIDTH_RATIO = 0.085
BAR_GAP_RATIO = 0.055
WAVEFORM_HEIGHT_RATIO = 0.52

PNG_SIZES = (32, 128, 256, 512)
ICO_SIZES = (16, 32, 48, 64, 256)


def _inside_rounded_square(x: float, y: float, size: float, radius: float) -> bool:
    """Whether a point falls inside a square with rounded corners."""
    left, top = radius, radius
    right, bottom = size - radius, size - radius

    nearest_x = min(max(x, left), right)
    nearest_y = min(max(y, top), bottom)

    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius**2


def _inside_waveform(x: float, y: float, size: float) -> bool:
    """Whether a point falls inside one of the rounded waveform bars."""
    bar_width = size * BAR_WIDTH_RATIO
    gap = size * BAR_GAP_RATIO
    total_width = len(BAR_HEIGHTS) * bar_width + (len(BAR_HEIGHTS) - 1) * gap
    start_x = (size - total_width) / 2
    centre_y = size / 2

    for index, height_ratio in enumerate(BAR_HEIGHTS):
        bar_left = start_x + index * (bar_width + gap)
        if not (bar_left <= x <= bar_left + bar_width):
            continue

        half_height = size * WAVEFORM_HEIGHT_RATIO * height_ratio / 2
        radius = bar_width / 2
        top = centre_y - half_height + radius
        bottom = centre_y + half_height - radius

        if top <= y <= bottom:
            return True

        # Rounded cap at whichever end the point is nearest.
        cap_y = top if y < top else bottom
        return (x - (bar_left + radius)) ** 2 + (y - cap_y) ** 2 <= radius**2

    return False


def _render(size: int) -> Pixels:
    """Draw the mark at ``size`` pixels, supersampled for smooth edges."""
    scale = size * SUPERSAMPLE
    radius = scale * CORNER_RADIUS_RATIO
    samples = SUPERSAMPLE * SUPERSAMPLE

    rows: Pixels = []
    for y in range(size):
        row: list[Colour] = []
        for x in range(size):
            totals = [0, 0, 0, 0]
            for sub_y in range(SUPERSAMPLE):
                for sub_x in range(SUPERSAMPLE):
                    point_x = x * SUPERSAMPLE + sub_x + 0.5
                    point_y = y * SUPERSAMPLE + sub_y + 0.5

                    if not _inside_rounded_square(point_x, point_y, scale, radius):
                        colour = TRANSPARENT
                    elif _inside_waveform(point_x, point_y, scale):
                        colour = FOREGROUND
                    else:
                        colour = BACKGROUND

                    for channel in range(4):
                        totals[channel] += colour[channel]

            row.append(
                (
                    totals[0] // samples,
                    totals[1] // samples,
                    totals[2] // samples,
                    totals[3] // samples,
                )
            )
        rows.append(row)
    return rows


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode_png(pixels: Pixels) -> bytes:
    """Encode 8-bit RGBA pixels as a PNG."""
    height = len(pixels)
    width = len(pixels[0])

    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0 (none)
        for red, green, blue, alpha in row:
            raw.extend((red, green, blue, alpha))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _encode_ico(images: dict[int, bytes]) -> bytes:
    """Pack PNG images into an ICO container.

    Windows has accepted PNG-compressed entries since Vista, which keeps the 256 pixel image
    from dominating the file the way a raw bitmap would.
    """
    count = len(images)
    directory = bytearray(struct.pack("<HHH", 0, 1, count))
    offset = 6 + 16 * count
    body = bytearray()

    for size, payload in sorted(images.items()):
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        body.extend(payload)
        offset += len(payload)

    return bytes(directory + body)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rendered = {size: _render(size) for size in sorted({*PNG_SIZES, *ICO_SIZES})}

    written: list[Path] = []
    for size in PNG_SIZES:
        # Tauri expects the retina variant named after its logical size.
        name = "128x128@2x.png" if size == 256 else f"{size}x{size}.png"
        path = OUTPUT_DIR / name
        path.write_bytes(_encode_png(rendered[size]))
        written.append(path)

    icon_path = OUTPUT_DIR / "icon.png"
    icon_path.write_bytes(_encode_png(rendered[512]))
    written.append(icon_path)

    ico_path = OUTPUT_DIR / "icon.ico"
    ico_path.write_bytes(_encode_ico({size: _encode_png(rendered[size]) for size in ICO_SIZES}))
    written.append(ico_path)

    for path in written:
        print(f"{path.relative_to(OUTPUT_DIR.parents[1])}  {path.stat().st_size:,} bytes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
