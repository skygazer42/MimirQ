"""Check exported asset integrity and create the downloadable identity package."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        self.paths.extend(v for k, v in attrs if k in ("src", "href") and v)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    output = args.assets.resolve()
    # Historical comparison pages are retained beside the kit, outside its exports.
    files = sorted(
        path for path in output.rglob("*") if path.is_file() and "blue-nature" not in path.relative_to(output).parts
    )
    report = {"svg": 0, "png": 0, "outlinedLettering": True, "localReferences": True}
    ns = {"svg": "http://www.w3.org/2000/svg"}
    for path in (path for path in files if path.suffix == ".svg"):
        root = ElementTree.parse(path).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg", path
        assert root.find(".//svg:text", ns) is None, f"Live font in {path}"
        assert root.find(".//svg:script", ns) is None, path
        report["svg"] += 1

    for path in (path for path in files if path.suffix == ".png"):
        with Image.open(path) as image:
            image.verify()
        report["png"] += 1

    for asset in json.loads((output / "assets.json").read_text(encoding="utf-8")):
        path = output / asset["file"]
        assert path.is_file(), path
        if path.suffix == ".png":
            with Image.open(path) as image:
                assert image.size == (asset["width"], asset["height"]), path

    for filename in ["mark-512.png", "logo@2x.png", "logo-inverse@2x.png", "logo-white@2x.png"]:
        with Image.open(output / filename) as image:
            alpha = image.convert("RGBA").getchannel("A")
            assert alpha.getextrema() == (0, 255), filename
            assert alpha.getpixel((0, 0)) == 0, filename
    report["transparentExports"] = True

    with Image.open(output / "favicon.ico") as image:
        assert image.ico.sizes() == {(16, 16), (32, 32), (48, 48)}
        for size in image.ico.sizes():
            image.ico.getimage(size).load()
    report["icoSizes"] = [16, 32, 48]

    with Image.open(output / "icon-maskable-512.png") as image:
        image = image.convert("RGB")
        background = image.getpixel((0, 0))
        for y in range(512):
            for x in range(512):
                if image.getpixel((x, y)) != background:
                    assert (x + 0.5 - 256) ** 2 + (y + 0.5 - 256) ** 2 <= 204.8**2
    report["maskableSafeCircle"] = True

    palette = json.loads((output / "tokens.json").read_text(encoding="utf-8"))["color"]

    def luminance(color):
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, [0.2126, 0.7152, 0.0722], strict=False))

    report["textContrast"] = {}
    for foreground, background in [
        ("ink", "fog"),
        ("muted", "fog"),
        ("rust", "fog"),
        ("white", "rust"),
        ("rustOnDark", "ink"),
    ]:
        values = sorted([luminance(palette[foreground]), luminance(palette[background])])
        ratio = (values[1] + 0.05) / (values[0] + 0.05)
        assert ratio >= 4.5, (foreground, background, ratio)
        report["textContrast"][f"{foreground}/{background}"] = round(ratio, 2)

    page = (output / "brandbook.html").read_text(encoding="utf-8")
    refs = References()
    refs.feed(page)
    local_files = refs.paths + re.findall(r"url\(['\"]?([^)'\"]+)", page)
    for ref in local_files:
        if ref.startswith(("#", "data:", "https://", "http://")):
            continue
        filename = ref.split("#")[0]
        if filename == "yuanxu-brand-kit.zip":
            continue
        path = output / filename
        assert path.is_file(), path
        if "#" in ref and filename.endswith(".svg"):
            target = ref.split("#", 1)[1]
            root = ElementTree.parse(path).getroot()
            assert any(element.get("id") == target for element in root.iter()), ref
    report["referencesChecked"] = len(local_files)

    archive = output / "yuanxu-brand-kit.zip"
    entries = {path.relative_to(output).as_posix(): path for path in files if path != archive}
    entries["README.md"] = args.guide
    for path in sorted(Path(__file__).parent.glob("*")):
        if path.is_file() and path.suffix in (".py", ".mjs"):
            entries["source/" + path.name] = path
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, path in sorted(entries.items()):
            bundle.write(path, name)
    with ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        report["packageFiles"] = len(bundle.namelist())
    report["archiveBytes"] = archive.stat().st_size
    report["passed"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    main()
