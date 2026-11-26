"""Draw the bitmaps of the Windows installer (NSIS) from the archive design's navy tokens, the
app tile and the wordmark, into packages/app/shell/src-tauri/windows/:

    sidebar.bmp            164x314   the step rail's background (bundle.windows.nsis.sidebarImage),
                                     with the tile and the wordmark at the bottom
    sidebar-125.bmp ...    the same rail at 125/150/175/200 % for high-DPI screens
    header.bmp             150x57    the uninstaller's page header (headerImage)

    python tools/installers/nsis_images.py

Needs Pillow. The tile is the approved dark app icon (icons/icon.png, 1024 px), scaled down to
48 px at 100 % and never below; the wordmark is Space Grotesk Medium from the archive fonts.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "packages" / "app" / "shell" / "src-tauri" / "windows"
TILE = ROOT / "packages" / "app" / "shell" / "src-tauri" / "icons" / "icon.png"
FONT = ROOT / "packages" / "app" / "ui" / "static" / "archive" / "fonts" / "space-grotesk-500.ttf"

# The archive tokens (navy), as in the design page's prototypes.
BG = (0x09, 0x12, 0x1D)       # --ar-bg
SURFACE = (0x11, 0x23, 0x32)  # --ar-surface: the rail
LINE = (0x54, 0x73, 0x83)     # --ar-line
FG = (0xEA, 0xF4, 0xF6)       # --ar-fg
DIM = (0x8E, 0xA3, 0xB0)      # --p-dim

SCALES = {"": 1.0, "-125": 1.25, "-150": 1.5, "-175": 1.75, "-200": 2.0}


def tile(size: int) -> Image.Image:
    image = Image.open(TILE).convert("RGBA")
    return image.resize((size, size), Image.LANCZOS)


def sidebar(scale: float) -> Image.Image:
    def px(value: float) -> int:
        return round(value * scale)

    width, height = px(164), px(314)
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)
    # The rail's right border, as the prototype's `border-right: 1px solid var(--ar-line)`.
    line = max(1, int(scale))  # as the installer scales 1 px: dpi * 1 // 96
    draw.rectangle([width - line, 0, width - 1, height - 1], fill=LINE)
    # The tile, then the wordmark under it, bottom-left with the rail's 16 px padding.
    size = px(48)
    font = ImageFont.truetype(str(FONT), px(17))
    words = "The Harness"
    left, top, right, bottom = draw.textbbox((0, 0), words, font=font)
    text_y = height - px(20) - bottom
    tile_y = text_y + top - px(12) - size
    image.paste(tile(size), (px(16), tile_y), tile(size))
    draw.text((px(16) - left, text_y), words, font=font, fill=FG)
    return image


def header() -> Image.Image:
    width, height = 150, 57
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    size = 48
    x = width - size - 4
    image.paste(tile(size), (x, (height - size) // 2), tile(size))
    font = ImageFont.truetype(str(FONT), 13)
    words = "The Harness"
    left, top, right, bottom = draw.textbbox((0, 0), words, font=font)
    draw.text((x - 10 - right, (height - bottom - top) // 2), words, font=font, fill=DIM)
    return image


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix, scale in SCALES.items():
        path = OUT / f"sidebar{suffix}.bmp"
        sidebar(scale).save(path, "BMP")
        print(path.relative_to(ROOT))
    path = OUT / "header.bmp"
    header().save(path, "BMP")
    print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
