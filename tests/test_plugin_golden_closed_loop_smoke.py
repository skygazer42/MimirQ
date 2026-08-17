
import pytest

from scripts.plugin_golden_closed_loop_smoke import select_plugin_ref


def _plugin(
    ref: str,
    *,
    test_status: str = "",
    published: bool = False,
    package_hash: str = "",
    executable: bool = True,
    golden: bool = True,
) -> dict:
    return {
        "refs": {"chunk": ref},
        "executable": executable,
        "contract": {"golden": {"enabled": golden}},
        "test_status": test_status,
        "published": published,
        "package_hash": package_hash,
    }


def test_select_plugin_ref_scores_candidates_and_keeps_first_tie() -> None:
    payload = {
        "items": [
            _plugin("plugin:first@1:chunk", test_status="passed", published=True),
            _plugin("plugin:lower@1:chunk", package_hash="hash"),
            _plugin("plugin:tied@1:chunk", test_status="passed", published=True),
            _plugin(
                "plugin:highest@1:chunk",
                test_status="passed",
                published=True,
                package_hash="hash",
            ),
        ]
    }

    assert select_plugin_ref(payload) == "plugin:highest@1:chunk"

    payload["items"].pop()
    assert select_plugin_ref(payload) == "plugin:first@1:chunk"


def test_select_plugin_ref_ignores_ineligible_and_malformed_items() -> None:
    payload = {
        "items": [
            None,
            {"refs": []},
            _plugin("", test_status="passed"),
            _plugin("plugin:not-executable@1:chunk", executable=False),
            _plugin("plugin:no-golden@1:chunk", golden=False),
            _plugin("  plugin:valid@1:chunk  "),
        ]
    }

    assert select_plugin_ref(payload) == "plugin:valid@1:chunk"


def test_select_plugin_ref_rejects_non_list_registry_items() -> None:
    with pytest.raises(RuntimeError, match=r"plugin list response must contain items\[\]"):
        select_plugin_ref({"items": {}})


def test_select_plugin_ref_includes_registry_error_hint_when_no_candidate() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"no executable pipeline plugin.*registry errors=\[\"broken registry\"\]",
    ):
        select_plugin_ref({"items": [], "errors": ["broken registry"]})
