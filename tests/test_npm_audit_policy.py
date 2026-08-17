from copy import deepcopy

from scripts.check_npm_audit import audit_policy_errors

_PACKAGE_JSON = {
    "dependencies": {"@docusaurus/core": "3.10.2"},
    "devDependencies": {},
}
_PACKAGE_LOCK = {
    "packages": {
        "": {"dependencies": {"@docusaurus/core": "3.10.2"}},
        "node_modules/@docusaurus/mdx-loader": {
            "version": "3.10.2",
            "dependencies": {"image-size": "^2.0.2"},
        },
        "node_modules/image-size": {"version": "2.0.2"},
    }
}


def _advisory(url: str) -> dict:
    return {
        "name": "image-size",
        "dependency": "image-size",
        "severity": "high",
        "range": "<=2.0.2",
        "url": url,
    }


def _report() -> dict:
    return {
        "metadata": {"vulnerabilities": {"high": 3, "critical": 0}},
        "vulnerabilities": {
            "image-size": {
                "severity": "high",
                "via": [
                    _advisory("https://github.com/advisories/GHSA-w3rx-r6r6-pgpr"),
                    _advisory("https://github.com/advisories/GHSA-5p2g-fcmc-qvqq"),
                ],
                "effects": ["@docusaurus/mdx-loader"],
                "nodes": ["node_modules/image-size"],
                "fixAvailable": False,
            },
            "@docusaurus/mdx-loader": {
                "severity": "high",
                "via": ["image-size"],
                "effects": ["@docusaurus/core"],
                "nodes": ["node_modules/@docusaurus/mdx-loader"],
                "fixAvailable": False,
            },
            "@docusaurus/core": {
                "severity": "high",
                "via": ["@docusaurus/mdx-loader"],
                "effects": [],
                "nodes": ["node_modules/@docusaurus/core"],
                "fixAvailable": False,
            },
        },
    }


def test_npm_audit_policy_allows_only_the_current_docusaurus_image_path() -> None:
    assert audit_policy_errors(_report(), _PACKAGE_JSON, _PACKAGE_LOCK) == []


def test_npm_audit_policy_rejects_an_unrelated_direct_advisory() -> None:
    report = _report()
    report["metadata"]["vulnerabilities"]["high"] = 4
    report["vulnerabilities"]["unexpected"] = {
        "severity": "high",
        "via": [{"name": "unexpected", "severity": "high"}],
        "nodes": ["node_modules/unexpected"],
        "fixAvailable": True,
    }

    assert audit_policy_errors(report, _PACKAGE_JSON, _PACKAGE_LOCK)


def test_npm_audit_policy_rejects_changed_advisory_or_counts() -> None:
    report = _report()
    report["vulnerabilities"]["image-size"]["via"][0]["range"] = "<=2.0.3"
    report["metadata"]["vulnerabilities"]["high"] = 4

    errors = audit_policy_errors(report, _PACKAGE_JSON, _PACKAGE_LOCK)

    assert any("unexpected image-size advisory" in error for error in errors)
    assert any("severe count mismatch" in error for error in errors)


def test_npm_audit_policy_rejects_runtime_or_additional_dependency_paths() -> None:
    package_json = deepcopy(_PACKAGE_JSON)
    package_json["dependencies"]["image-size"] = "2.0.2"
    package_lock = deepcopy(_PACKAGE_LOCK)
    package_lock["packages"]["node_modules/other"] = {"dependencies": {"image-size": "2.0.2"}}

    errors = audit_policy_errors(_report(), package_json, package_lock)

    assert any("must not be a direct" in error for error in errors)
    assert any("dependency parents" in error for error in errors)


def test_npm_audit_policy_rejects_unrooted_propagation() -> None:
    report = _report()
    report["vulnerabilities"]["@docusaurus/core"]["via"] = ["unrelated"]

    errors = audit_policy_errors(report, _PACKAGE_JSON, _PACKAGE_LOCK)

    assert any("unexpected high/critical advisory path" in error for error in errors)


def test_npm_audit_policy_reports_malformed_inputs_without_hiding_lock_errors() -> None:
    errors = audit_policy_errors(
        {"metadata": [], "vulnerabilities": None},
        {"dependencies": {"image-size": "2.0.2"}, "devDependencies": []},
        {"packages": []},
    )

    assert errors == [
        "image-size must not be a direct docs dependency: dependencies",
        "invalid docs package section: devDependencies",
        "invalid docs package-lock packages",
        "invalid or incomplete npm audit response",
    ]


def test_npm_audit_policy_reports_invalid_severe_entries_and_summary() -> None:
    report = _report()
    report["metadata"]["vulnerabilities"] = {"high": "3", "critical": 0}
    report["vulnerabilities"][42] = "broken"

    errors = audit_policy_errors(report, _PACKAGE_JSON, _PACKAGE_LOCK)

    assert "invalid npm audit vulnerability: 42='broken'" in errors
    assert any("npm audit severe count mismatch" in error for error in errors)


def test_npm_audit_policy_preserves_direct_advisory_validation_errors() -> None:
    report = _report()
    image_size = report["vulnerabilities"]["image-size"]
    image_size["nodes"] = ["node_modules/unexpected"]
    image_size["fixAvailable"] = {"name": "image-size"}
    image_size["via"][0]["dependency"] = "unexpected"

    errors = audit_policy_errors(report, _PACKAGE_JSON, _PACKAGE_LOCK)

    assert any("unexpected npm audit nodes for image-size" in error for error in errors)
    assert any("image-size unexpectedly has a fix" in error for error in errors)
    assert any("unexpected image-size advisory" in error for error in errors)
    assert any("unexpected allowed image-size advisories" in error for error in errors)
