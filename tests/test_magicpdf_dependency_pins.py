from pathlib import Path


def test_magicpdf_pins_stringzilla_to_binary_wheel_release():
    requirements = (
        Path(__file__).resolve().parents[1] / "docker" / "magicpdf" / "requirements.txt"
    ).read_text(encoding="utf-8").splitlines()

    assert "stringzilla==4.6.1" in requirements
