from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MAKEFILE = "plugins/pipelines/changzhou-gov-service-knowledge/changzhou-gov-service-knowledge.mk"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_core_makefile_optionally_includes_changzhou_plugin_commands() -> None:
    makefile = _read("Makefile")

    assert "PLUGIN_HELP_TARGETS ?=" in makefile
    assert f"CHANGZHOU_GOV_PLUGIN_MAKEFILE := {PLUGIN_MAKEFILE}" in makefile
    assert "-include $(wildcard $(CHANGZHOU_GOV_PLUGIN_MAKEFILE))" in makefile
    assert "@for target in $(PLUGIN_HELP_TARGETS)" in makefile


def test_changzhou_specific_targets_and_defaults_live_in_plugin_makefile() -> None:
    core_makefile = _read("Makefile")
    plugin_makefile = _read(PLUGIN_MAKEFILE)

    assert "CHANGZHOU_DIFY_APP_ID ?=" not in core_makefile
    assert "changzhou-dify-external-probe:" not in core_makefile
    assert "CHANGZHOU_DIFY_APP_ID ?=" in plugin_makefile
    assert "changzhou-dify-external-probe:" in plugin_makefile
    assert "changzhou-gov-plugin-chunk-report:" in plugin_makefile


def test_core_makefile_keeps_generic_targets_decoupled_from_changzhou_defaults() -> None:
    makefile = _read("Makefile")
    plugin_makefile = _read(PLUGIN_MAKEFILE)

    assert "DIFY_CONSOLE_STORAGE_STATE ?= /tmp/dify_console_storage_state.json" in makefile
    assert "MIXED_RAG_CASES ?=" not in makefile
    assert "plugin-release-gate:" in makefile
    assert "mixed-rag-quality:" in makefile
    assert "MIXED_RAG_CASES ?= plugins/pipelines/changzhou-gov-service-knowledge/" in plugin_makefile
