import pytest


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://drive.google.com/file/d/FILEID/view?usp=sharing", "FILEID"),
        ("https://drive.google.com/open?id=FILEID", "FILEID"),
        ("https://drive.google.com/uc?id=FILEID&export=download", "FILEID"),
        ("https://example.com/not-drive", None),
    ],
)
def test_extract_drive_file_id(url: str, expected: str | None) -> None:
    from app.api.v1.connectors import _extract_drive_file_id

    assert _extract_drive_file_id(url) == expected


def test_drive_direct_download_url() -> None:
    from app.api.v1.connectors import _drive_direct_download_url

    assert _drive_direct_download_url("FILEID") == "https://drive.google.com/uc?export=download&id=FILEID"


def test_github_raw_url_encodes_branch_and_path() -> None:
    from app.api.v1.connectors import _github_raw_url

    url = _github_raw_url(owner="octo", repo="hello", branch="feature/x", path="docs/a b.md")
    assert url == "https://raw.githubusercontent.com/octo/hello/feature%2Fx/docs/a%20b.md"

