import pytest

from scripts.check_pnpm_audit import audit_policy_errors

_PACKAGE_JSON = {
    "dependencies": {"@sentry/nextjs": "^10.66.0"},
    "devDependencies": {
        "eslint": "^9.39.4",
        "eslint-config-next": "16.2.11",
        "openapi-typescript": "7.13.0",
    },
}


def _report(path: str, *, version: str = "1.1.16", high: int = 1) -> dict:
    return {
        "metadata": {"vulnerabilities": {"high": high, "critical": 0}},
        "advisories": {
            "1124334": {
                "github_advisory_id": "GHSA-mh99-v99m-4gvg",
                "severity": "high",
                "findings": [{"version": version, "paths": [path]}],
            }
        },
    }


@pytest.mark.parametrize(
    ("version", "path"),
    [
        (
            "1.1.16",
            ". > eslint@9.39.4 > @eslint/config-array@0.21.2 > minimatch@3.1.5 > brace-expansion@1.1.16",
        ),
        (
            "1.1.16",
            ". > eslint-config-next@16.2.11 > typescript-eslint@8.65.0 > "
            "@typescript-eslint/eslint-plugin@8.65.0 > @typescript-eslint/type-utils@8.65.0 > "
            "@typescript-eslint/utils@8.65.0 > @eslint-community/eslint-utils@4.10.1 > "
            "eslint@9.39.4 > @eslint/eslintrc@3.3.5 > minimatch@3.1.5 > brace-expansion@1.1.16",
        ),
        (
            "2.1.2",
            ". > openapi-typescript@7.13.0 > @redocly/openapi-core@1.34.6 > "
            "minimatch@5.1.9 > brace-expansion@2.1.2",
        ),
        ("1.1.16", ".>eslint>minimatch>brace-expansion"),
        ("2.1.2", ".>openapi-typescript>@redocly/openapi-core>minimatch>brace-expansion"),
    ],
)
def test_pnpm_audit_policy_allows_current_tooling_path_families(version: str, path: str) -> None:
    assert audit_policy_errors(_report(path, version=version), _PACKAGE_JSON) == []


@pytest.mark.parametrize(
    "path",
    [
        ". > @sentry/nextjs@10.66.0 > glob@13.0.6 > minimatch@10.2.5 > brace-expansion@1.1.16",
        ". > eslint-config-next@16.2.11 > unknown-plugin@1.0.0 > minimatch@3.1.5 > brace-expansion@1.1.16",
        ".>@sentry/nextjs>glob>minimatch>brace-expansion",
        ".>eslint-config-next>unknown-plugin>minimatch>brace-expansion",
    ],
)
def test_pnpm_audit_policy_rejects_runtime_and_unknown_chains(path: str) -> None:
    assert audit_policy_errors(_report(path), _PACKAGE_JSON)


def test_pnpm_audit_policy_rejects_changed_versions_and_runtime_roots() -> None:
    path = ". > eslint@9.39.4 > minimatch@3.1.5 > brace-expansion@1.1.16"
    assert audit_policy_errors(_report(path, version="1.1.15"), _PACKAGE_JSON)

    for section in ("dependencies", "optionalDependencies"):
        runtime_package = {**_PACKAGE_JSON, section: {"eslint": "^9.39.4"}}
        assert audit_policy_errors(_report(path), runtime_package)


def test_pnpm_audit_policy_rejects_report_count_mismatch() -> None:
    path = ". > eslint@9.39.4 > minimatch@3.1.5 > brace-expansion@1.1.16"
    assert audit_policy_errors(_report(path, high=2), _PACKAGE_JSON)
