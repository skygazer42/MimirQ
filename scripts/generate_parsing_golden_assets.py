from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from PIL import Image, ImageDraw


def _write_qr(path: Path, value: str) -> None:
    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode(value).astype("uint8")
    qr = cv2.copyMakeBorder(qr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    qr = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(path), qr)


def _write_barcode(path: Path, value12: str) -> None:
    l_codes = {"0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011", "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011"}
    g_codes = {"0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101", "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111"}
    r_codes = {"0": "1110010", "1": "1100110", "2": "1101100", "3": "1000010", "4": "1011100", "5": "1001110", "6": "1010000", "7": "1000100", "8": "1001000", "9": "1110100"}
    parity_patterns = {"0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG", "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL"}

    def checksum12(raw: str) -> str:
        total = 0
        for index, ch in enumerate(raw, start=1):
            digit = int(ch)
            total += digit if index % 2 == 1 else 3 * digit
        return str((10 - (total % 10)) % 10)

    full = value12 + checksum12(value12)
    bits = "101"
    for digit, parity in zip(full[1:7], parity_patterns[full[0]], strict=True):
        bits += l_codes[digit] if parity == "L" else g_codes[digit]
    bits += "01010"
    for digit in full[7:]:
        bits += r_codes[digit]
    bits += "101"

    module = 4
    quiet_zone = 12
    width = (len(bits) + quiet_zone * 2) * module
    height = 160
    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    cursor = quiet_zone * module
    for bit in bits:
        if bit == "1":
            draw.rectangle([cursor, 0, cursor + module - 1, height - 1], fill=0)
        cursor += module
    image.save(path)


def _write_chart(path: Path) -> None:
    image = Image.new("RGB", (256, 160), color=(248, 250, 252))
    draw = ImageDraw.Draw(image)
    draw.rectangle([24, 20, 232, 132], outline=(148, 163, 184), width=2)
    draw.line([40, 120, 40, 36, 216, 36], fill=(148, 163, 184), width=2)
    bars = [(68, 92), (104, 72), (140, 54), (176, 46)]
    for x, top in bars:
        draw.rectangle([x, top, x + 18, 120], fill=(59, 130, 246))
    image.save(path)


def _write_diagram(path: Path) -> None:
    image = Image.new("RGB", (256, 160), color=(250, 250, 249))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([28, 24, 108, 60], radius=8, outline=(71, 85, 105), width=2)
    draw.rounded_rectangle([148, 24, 228, 60], radius=8, outline=(71, 85, 105), width=2)
    draw.rounded_rectangle([88, 96, 168, 132], radius=8, outline=(71, 85, 105), width=2)
    draw.line([108, 42, 148, 42], fill=(71, 85, 105), width=2)
    draw.line([128, 60, 128, 96], fill=(71, 85, 105), width=2)
    draw.line([188, 60, 128, 96], fill=(71, 85, 105), width=2)
    draw.line([68, 60, 128, 96], fill=(71, 85, 105), width=2)
    image.save(path)


def generate_assets(output_root: Path) -> None:
    targets = [
        (output_root / "qr_sheet" / "input" / "qr.png", lambda path: _write_qr(path, "HELLO-QR")),
        (output_root / "qr_sheet" / "golden" / "qr.png", lambda path: _write_qr(path, "HELLO-QR")),
        (output_root / "barcode_label" / "input" / "barcode.png", lambda path: _write_barcode(path, "590123412345")),
        (output_root / "barcode_label" / "golden" / "barcode.png", lambda path: _write_barcode(path, "590123412345")),
        (output_root / "table_scan" / "input" / "chart.png", _write_chart),
        (output_root / "table_scan" / "golden" / "chart.png", _write_chart),
        (output_root / "diagram_page" / "input" / "diagram.png", _write_diagram),
        (output_root / "diagram_page" / "golden" / "diagram.png", _write_diagram),
    ]
    for path, writer in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic image assets for parser benchmark root fixtures.")
    parser.add_argument(
        "--output-root",
        default="tests/fixtures/parsing_golden",
        help="Root fixture directory to populate (default: tests/fixtures/parsing_golden)",
    )
    args = parser.parse_args(argv)

    output_root = Path(str(args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    generate_assets(output_root)
    print(f"[generate-parsing-golden-assets] wrote assets under {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
