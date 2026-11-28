"""Generate the approved Yuanxu identity from one geometric source.

Requires fonttools and brotli for outlining/subsetting Noto Sans SC.
Raster exports are produced separately by render.mjs; neither tool is an app dependency.
"""

from __future__ import annotations

import argparse
import html
import json
from functools import lru_cache
from pathlib import Path

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "web").is_dir() and (p / "docs").is_dir()),
    Path.cwd(),
)
OUT = ROOT / "web/public/brand/yuanxu"
INK = "#20262E"
RUST = "#B84A2A"
FOG = "#F6F7F8"
WHITE = "#FFFFFF"
LINE = "#DDE1E4"
SOFT = "#F9ECE6"
MUTED = "#606A75"
INVERSE_RUST = "#F09A77"

PALETTE = {
    "ink": INK,
    "rust": RUST,
    "fog": FOG,
    "white": WHITE,
    "line": LINE,
    "selected": SOFT,
    "muted": MUTED,
    "rustOnDark": INVERSE_RUST,
}


def svg(width: int, height: int, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f"<title>{html.escape(title)}</title>{body}</svg>\n"
    )


def mark(main: str = INK, accent: str = RUST) -> str:
    """48-unit painted mark on a 64-unit canvas, with an 8-unit minimum gap."""
    return (
        f'<path fill="{main}" d="M8 8H56V20H20V32H8Z"/>'
        f'<path fill="{main}" d="M28 28H56V56H44V40H28Z"/>'
        f'<path fill="{accent}" d="M8 44H32V56H8Z"/>'
    )


LATIN = {
    "Y": "M0 0H4.6L10 9.2L15.4 0H20L12 13.3V28H8V13.3Z",
    "U": "M0 0H4V20Q4 24 8 24H12Q16 24 16 20V0H20V20Q20 28 12 28H8Q0 28 0 20Z",
    "A": "M0 28L8 0H12L20 28H15.8L13.3 19H6.7L4.2 28ZM7.8 15H12.2L10 7Z",
    "N": "M0 28V0H4L16 20V0H20V28H16L4 8V28Z",
    "X": "M0 0H4.6L10 9.6L15.4 0H20L12.3 14L20 28H15.4L10 18.4L4.6 28H0L7.7 14Z",
}


def latin(x: float, y: float, height: float, fill: str = INK) -> str:
    scale = height / 28
    paths = "".join(f'<path transform="translate({i * 28} 0)" d="{LATIN[c]}"/>' for i, c in enumerate("YUANXU"))
    return f'<g transform="translate({x} {y}) scale({scale})" fill="{fill}" fill-rule="evenodd">{paths}</g>'


class Outlines:
    def __init__(self, font_path: str):
        self.font = TTFont(font_path)
        self.cmap = self.font.getBestCmap()
        self.upm = self.font["head"].unitsPerEm

    @lru_cache(maxsize=2048)
    def glyph(self, char: str, weight: int):
        glyphset = self.font.getGlyphSet(location={"wght": weight})
        name = self.cmap[ord(char)]
        glyph = glyphset[name]
        pen = SVGPathPen(glyphset)
        glyph.draw(pen)
        bounds = BoundsPen(glyphset)
        glyph.draw(bounds)
        return pen.getCommands(), glyph.width, bounds.bounds

    def text(self, text: str, x: float, y: float, size: float, fill=INK, weight=500, tracking=0):
        # Coordinates use a consistent baseline, not each character's bounding box.
        paths = []
        offset = 0
        scale = size / self.upm
        for char in text:
            if char == " ":
                offset += size * 0.28
                continue
            path, advance, _ = self.glyph(char, weight)
            paths.append(
                f'<path transform="translate({x + offset:.3f} {y:.3f}) scale({scale:.6f} {-scale:.6f})" d="{path}"/>'
            )
            offset += advance * scale + tracking
        return f'<g fill="{fill}">{"".join(paths)}</g>'


ICONS = {
    "knowledge": ("知识库", '<path d="M4 4H10L12 6H20V20H4Z"/><path d="M8 10H16M8 14H14"/>'),
    "governance": ("数据治理", '<path d="M4 6H20M4 12H20M4 18H20"/><path d="M8 3V9M16 9V15M10 15V21"/>'),
    "retrieval": ("检索", '<path d="M10 3H16V15H4V3Z"/><path d="M7 7H13M7 11H11M15 15L21 21"/>'),
    "citation": ("引用", '<path d="M3 4H10V12H7V20H3ZM14 4H21V12H18V20H14Z"/>'),
    "evaluation": ("回归评测", '<path d="M4 4H20V20H4Z"/><path d="M7 12L10 15L17 8"/>'),
    "trace": ("链路追踪", '<path d="M4 4H10V10H4ZM14 14H20V20H14Z"/><path d="M10 7H17V14"/>'),
}


def icon(name: str, x=0, y=0, size=24, color="currentColor") -> str:
    return (
        f'<g transform="translate({x} {y}) scale({size / 24})" '
        f'fill="none" stroke="{color}" stroke-width="1.75" '
        f'stroke-linecap="square" stroke-linejoin="miter">{ICONS[name][1]}</g>'
    )


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default="C:/Windows/Fonts/NotoSansSC-VF.ttf")
    parser.add_argument("--font-license", required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icons").mkdir(exist_ok=True)
    (OUT / "fonts").mkdir(exist_ok=True)
    outlines = Outlines(args.font)
    assets = []

    def write(name, width, height, body, title):
        (OUT / name).write_text(svg(width, height, body, title), encoding="utf-8")
        assets.append({"file": name, "width": width, "height": height, "label": title})

    def lockup(main=INK, accent=RUST):
        return mark(main, accent) + outlines.text("原序", 80, 43, 44, main, 650, 3) + latin(83, 54, 10, main)

    variants = {
        "": (INK, RUST),
        "-inverse": (FOG, INVERSE_RUST),
        "-ink": (INK, INK),
        "-white": (WHITE, WHITE),
        "-rust": (RUST, RUST),
    }
    for suffix, colors in variants.items():
        write(f"mark{suffix}.svg", 64, 64, mark(*colors), f"原序标志{suffix}")
        write(f"logo{suffix}.svg", 184, 72, lockup(*colors), f"原序中英组合标志{suffix}")

    write("wordmark-zh.svg", 104, 56, outlines.text("原序", 3, 44, 44, INK, 650, 3), "原序中文字标")
    write("wordmark-en.svg", 176, 44, latin(6, 8, 28), "YUANXU 英文字标")
    write("logo-en.svg", 272, 72, mark() + latin(84, 22, 28), "原序英文组合标志")
    write("logo-compact.svg", 184, 64, mark() + outlines.text("原序", 80, 46, 44, INK, 650, 3), "原序紧凑组合标志")
    write(
        "logo-compact-inverse.svg",
        184,
        64,
        mark(FOG, INVERSE_RUST) + outlines.text("原序", 80, 46, 44, FOG, 650, 3),
        "原序紧凑组合标志反白",
    )
    write(
        "logo-stacked.svg",
        192,
        200,
        f'<g transform="translate(48 0) scale(1.5)">{mark()}</g>'
        + outlines.text("原序", 43, 148, 48, INK, 650, 4)
        + latin(54, 167, 15),
        "原序纵向组合标志",
    )

    # Square platform sources have no baked-in rounded corners. The OS supplies its mask.
    app_dark = f'<path fill="{INK}" d="M0 0H512V512H0Z"/><g transform="translate(32 32) scale(7)">{mark(FOG, INVERSE_RUST)}</g>'
    app_light = f'<path fill="{FOG}" d="M0 0H512V512H0Z"/><g transform="translate(32 32) scale(7)">{mark()}</g>'
    app_maskable = f'<path fill="{INK}" d="M0 0H512V512H0Z"/><g transform="translate(64 64) scale(6)">{mark(FOG, INVERSE_RUST)}</g>'
    write("app-icon.svg", 512, 512, app_dark, "原序深色应用图标")
    write("app-icon-light.svg", 512, 512, app_light, "原序浅色应用图标")
    write("app-icon-maskable.svg", 512, 512, app_maskable, "原序可遮罩应用图标")

    # At 16px all painted edges and gaps align to whole pixels.
    adaptive = (
        "<style>.main{fill:#20262e}.accent{fill:#b84a2a}"
        "@media(prefers-color-scheme:dark){.main{fill:#f6f7f8}.accent{fill:#f09a77}}</style>"
        '<path class="main" d="M1 1H15V4H4V8H1ZM8 7H15V15H12V10H8Z"/>'
        '<path class="accent" d="M1 12H8V15H1Z"/>'
    )
    write("favicon.svg", 16, 16, adaptive, "原序自适应标签页图标")

    for name, (label, _) in ICONS.items():
        write(f"icons/{name}.svg", 24, 24, icon(name), f"原序 · {label}")
    symbols = "".join(f'<symbol id="yuanxu-{name}" viewBox="0 0 24 24">{icon(name)}</symbol>' for name in ICONS)
    (OUT / "icons/sprite.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg">{symbols}</svg>\n', encoding="utf-8"
    )

    # The overview is a real vector board. All visible lettering is outlined.
    board = [
        f'<path fill="{INK}" d="M0 0H1600V1060H0Z"/>',
        f'<path fill="{FOG}" d="M24 24H1048V552H24Z"/>',
        '<path fill="#2C333C" d="M1072 24H1576V552H1072Z"/>',
        f'<path fill="{WHITE}" d="M24 576H520V936H24Z"/>',
        f'<path fill="{FOG}" d="M544 576H1048V936H544Z"/>',
        f'<path fill="{WHITE}" d="M1072 576H1576V936H1072Z"/>',
        f'<g transform="translate(80 80) scale(2.3)">{lockup()}</g>',
        outlines.text("从原始资料，", 90, 354, 48, INK, 500),
        outlines.text("到可信答案。", 90, 420, 48, INK, 500),
        outlines.text("原序品牌识别系统", 90, 505, 20, MUTED, 450),
        f'<g transform="translate(1184 104) scale(4.4)">{mark(FOG, INVERSE_RUST)}</g>',
        latin(1216, 454, 38, FOG),
        outlines.text("深底强调 · #F09A77", 1104, 516, 20, "#D9DEE3", 500),
        outlines.text("形从秩序而来", 56, 621, 22, INK, 550),
    ]
    for unit in range(-28, 96, 4):
        x = 152 + unit * 3.8
        y = 638 + unit * 3.8
        if 56 <= x <= 496:
            board.append(f'<path d="M{x:.1f} 654V878" stroke="{LINE}" stroke-width="1"/>')
        if 654 <= y <= 878:
            board.append(f'<path d="M56 {y:.1f}H496" stroke="{LINE}" stroke-width="1"/>')
    board.extend(
        [
            f'<g transform="translate(152 638) scale(3.8)">{mark()}</g>',
            outlines.text("12 单位笔画 · 最小间隙 8", 56, 909, 18, MUTED, 450),
            outlines.text("一套图标，同一种语法", 576, 621, 22, INK, 550),
        ]
    )
    for i, (name, (label, _)) in enumerate(ICONS.items()):
        x = 596 + (i % 3) * 150
        y = 680 + (i // 3) * 122
        board.extend(
            [
                icon(name, x + 17, y, 44, INK),
                outlines.text(label, x - 2, y + 74, 18, MUTED, 450),
            ]
        )
    board.extend(
        [
            outlines.text("从应用到每个像素", 1104, 621, 22, INK, 550),
            f'<rect x="1112" y="670" width="136" height="136" rx="30" fill="{INK}"/>',
            f'<g transform="translate(1120.5 678.5) scale(1.859375)">{mark(FOG, INVERSE_RUST)}</g>',
            f'<rect x="1280" y="694" width="88" height="88" rx="20" fill="{FOG}"/>',
            f'<g transform="translate(1285.5 699.5) scale(1.203125)">{mark()}</g>',
            f'<g transform="translate(1404 724) scale(.5)">{mark()}</g>',
            f'<g transform="translate(1468 730) scale(.25)">{mark(INK, INK)}</g>',
            outlines.text("应用图标", 1112, 851, 18, MUTED, 450),
            outlines.text("32px", 1402, 851, 16, MUTED, 450),
            outlines.text("16px", 1466, 851, 16, MUTED, 450),
            latin(1112, 884, 20),
        ]
    )
    swatches = [(FOG, INK, "雾白", "#F6F7F8"), (INK, FOG, "深墨", "#20262E"), (RUST, WHITE, "赭橙", "#B84A2A")]
    for i, (bg, fg, name, code) in enumerate(swatches):
        x = 24 + i * 520
        board.extend(
            [
                f'<path fill="{bg}" d="M{x} 960H{x + 512}V1036H{x}Z"/>',
                outlines.text(name, x + 24, 1008, 23, fg, 550),
                outlines.text(code, x + 340, 1007, 20, fg, 450),
            ]
        )
    write("brand-overview.svg", 1600, 1060, "".join(board), "原序品牌识别总览")

    social = (
        f'<path fill="{FOG}" d="M0 0H1200V630H0Z"/>'
        f'<g transform="translate(64 64) scale(1.8)">{lockup()}</g>'
        + outlines.text("从原始资料，", 80, 346, 60, INK, 500)
        + outlines.text("到可信答案。", 80, 430, 60, INK, 500)
        + f'<g transform="translate(832 180) scale(4)">{mark()}</g>'
        + f'<path fill="{RUST}" d="M80 536H1120V540H80Z"/>'
    )
    write("social-card.svg", 1200, 630, social, "原序分享封面")

    (OUT / "tokens.json").write_text(
        json.dumps(
            {
                "brand": {"name": "原序", "latin": "YUANXU", "tagline": "从原始资料，到可信答案。"},
                "color": PALETTE,
                "geometry": {
                    "canvas": 64,
                    "paintedBounds": [8, 8, 56, 56],
                    "stroke": 12,
                    "minimumGap": 8,
                    "clearSpace": 12,
                },
                "icon": {"canvas": 24, "stroke": 1.75, "linecap": "square", "linejoin": "miter"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "tokens.css").write_text(
        "/** Approved Yuanxu brand colors; product state colors remain separate. */\n"
        + ":root {\n"
        + "".join(f"  --yuanxu-{k}: {v};\n" for k, v in PALETTE.items())
        + "}\n",
        encoding="utf-8",
    )
    (OUT / "assets.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "fonts/OFL.txt").write_bytes(Path(args.font_license).read_bytes())

    # Only a small, explicitly scoped font subset is distributed for the brand guide.
    preview_text = (
        "原序品牌识别系统从原始资料到可信答案源线归序标志字标应用图标功能图标"
        "下载完整品牌包查看资产规范主标志浅色深色单色反白英文组合中文字标安全距离"
        "最小尺寸色彩字体深墨雾白赭橙清晰可控有据知识库数据治理检索引用回归评测"
        "链路追踪形从秩序而来一套图标同一种语法从应用到每个像素透明背景矢量"
        "浅底深底分享封面颜色复制已复制复制失败请手动选择相同几何多个场景来源"
        "定位间隙笔画单位资料文档图片状态语义独立使用指南资产目录版本维护桌面手机"
        "，。· /()0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#-+→"
    )
    font = TTFont(args.font)
    if (OUT / "brandbook.html").exists():
        preview_text += (OUT / "brandbook.html").read_text(encoding="utf-8")
    options = subset.Options()
    options.flavor = "woff2"
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    sub = subset.Subsetter(options=options)
    sub.populate(text=preview_text)
    sub.subset(font)
    font.flavor = "woff2"
    font.save(OUT / "fonts/noto-sans-sc-brand.woff2")
    print(f"Generated {len(assets)} SVG assets, tokens and brand-guide font in {OUT}")  # noqa: T201


if __name__ == "__main__":
    main()
