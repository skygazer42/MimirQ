"""Allow one unfixed pnpm advisory only on exact development-tool paths."""

import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

_ALLOWED_GHSA = "GHSA-mh99-v99m-4gvg"
_ALLOWED_ROOTS = {
    "eslint@9.39.4": ("eslint", "^9.39.4"),
    "eslint-config-next@16.2.11": ("eslint-config-next", "16.2.11"),
    "openapi-typescript@7.13.0": ("openapi-typescript", "7.13.0"),
}
_ESLINT_ROOTS = {"eslint@9.39.4", "eslint-config-next@16.2.11"}
_ESLINT_TERMINAL = ("minimatch@3.1.5", "brace-expansion@1.1.16")
_OPENAPI_PATH = (
    "openapi-typescript@7.13.0",
    "@redocly/openapi-core@1.34.6",
    "minimatch@5.1.9",
    "brace-expansion@2.1.2",
)
_ESLINT_EDGES = {
    ("@eslint-community/eslint-utils@4.10.1", "eslint@9.39.4"),
    ("@eslint/config-array@0.21.2", "minimatch@3.1.5"),
    ("@eslint/eslintrc@3.3.5", "minimatch@3.1.5"),
    ("@typescript-eslint/eslint-plugin@8.65.0", "@typescript-eslint/parser@8.65.0"),
    ("@typescript-eslint/eslint-plugin@8.65.0", "@typescript-eslint/type-utils@8.65.0"),
    ("@typescript-eslint/eslint-plugin@8.65.0", "@typescript-eslint/utils@8.65.0"),
    ("@typescript-eslint/eslint-plugin@8.65.0", "eslint@9.39.4"),
    ("@typescript-eslint/parser@8.65.0", "eslint@9.39.4"),
    ("@typescript-eslint/type-utils@8.65.0", "@typescript-eslint/utils@8.65.0"),
    ("@typescript-eslint/type-utils@8.65.0", "eslint@9.39.4"),
    ("@typescript-eslint/utils@8.65.0", "@eslint-community/eslint-utils@4.10.1"),
    ("@typescript-eslint/utils@8.65.0", "eslint@9.39.4"),
    ("eslint-config-next@16.2.11", "eslint-import-resolver-typescript@3.10.1"),
    ("eslint-config-next@16.2.11", "eslint-plugin-import@2.32.0"),
    ("eslint-config-next@16.2.11", "eslint-plugin-jsx-a11y@6.10.2"),
    ("eslint-config-next@16.2.11", "eslint-plugin-react-hooks@7.1.1"),
    ("eslint-config-next@16.2.11", "eslint-plugin-react@7.37.5"),
    ("eslint-config-next@16.2.11", "eslint@9.39.4"),
    ("eslint-config-next@16.2.11", "typescript-eslint@8.65.0"),
    ("eslint-import-resolver-typescript@3.10.1", "eslint-plugin-import@2.32.0"),
    ("eslint-import-resolver-typescript@3.10.1", "eslint@9.39.4"),
    ("eslint-module-utils@2.14.0", "@typescript-eslint/parser@8.65.0"),
    ("eslint-module-utils@2.14.0", "eslint@9.39.4"),
    ("eslint-plugin-import@2.32.0", "@typescript-eslint/parser@8.65.0"),
    ("eslint-plugin-import@2.32.0", "eslint-module-utils@2.14.0"),
    ("eslint-plugin-import@2.32.0", "eslint@9.39.4"),
    ("eslint-plugin-import@2.32.0", "minimatch@3.1.5"),
    ("eslint-plugin-jsx-a11y@6.10.2", "eslint@9.39.4"),
    ("eslint-plugin-jsx-a11y@6.10.2", "minimatch@3.1.5"),
    ("eslint-plugin-react-hooks@7.1.1", "eslint@9.39.4"),
    ("eslint-plugin-react@7.37.5", "eslint@9.39.4"),
    ("eslint-plugin-react@7.37.5", "minimatch@3.1.5"),
    ("eslint@9.39.4", "@eslint/config-array@0.21.2"),
    ("eslint@9.39.4", "@eslint/eslintrc@3.3.5"),
    ("eslint@9.39.4", "minimatch@3.1.5"),
    ("minimatch@3.1.5", "brace-expansion@1.1.16"),
    ("typescript-eslint@8.65.0", "@typescript-eslint/eslint-plugin@8.65.0"),
    ("typescript-eslint@8.65.0", "@typescript-eslint/parser@8.65.0"),
    ("typescript-eslint@8.65.0", "@typescript-eslint/utils@8.65.0"),
    ("typescript-eslint@8.65.0", "eslint@9.39.4"),
}


def _path_errors(path: Any, version: Any, package_json: dict[str, Any]) -> set[str]:
    if not isinstance(path, str) or not path.startswith(". > "):
        return {f"invalid {_ALLOWED_GHSA} path: {path!r}"}

    chain = tuple(path.split(" > ")[1:])
    root = chain[0]
    root_policy = _ALLOWED_ROOTS.get(root)
    if root_policy is None:
        return {f"unexpected {_ALLOWED_GHSA} root: {root}"}

    errors: set[str] = set()
    package_name, package_spec = root_policy
    dependencies = package_json.get("dependencies")
    dev_dependencies = package_json.get("devDependencies")
    optional_dependencies = package_json.get("optionalDependencies", {})
    if not all(isinstance(section, dict) for section in (dependencies, dev_dependencies, optional_dependencies)):
        return {"invalid web package dependency declarations"}
    if (
        dev_dependencies.get(package_name) != package_spec
        or package_name in dependencies
        or package_name in optional_dependencies
    ):
        errors.add(f"allowed audit root is not dev-only: {package_name}@{package_spec}")

    if version == "2.1.2":
        if chain != _OPENAPI_PATH:
            errors.add(f"unexpected {_ALLOWED_GHSA} OpenAPI path: {path}")
        return errors
    if version != "1.1.16" or root not in _ESLINT_ROOTS or chain[-2:] != _ESLINT_TERMINAL:
        errors.add(f"unexpected {_ALLOWED_GHSA} version/path: {version} {path}")
        return errors
    for edge in pairwise(chain):
        if edge not in _ESLINT_EDGES:
            errors.add(f"unexpected {_ALLOWED_GHSA} dependency edge: {' > '.join(edge)}")
    return errors


def audit_policy_errors(report: dict[str, Any], package_json: dict[str, Any]) -> list[str]:
    advisories = report.get("advisories")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(advisories, dict):
        return ["invalid or incomplete pnpm audit response"]

    vulnerabilities = metadata.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        return ["invalid pnpm audit vulnerability summary"]

    errors: set[str] = set()
    observed = {"high": 0, "critical": 0}
    for advisory in advisories.values():
        if not isinstance(advisory, dict) or advisory.get("github_advisory_id") != _ALLOWED_GHSA:
            errors.add(f"unexpected advisory: {advisory!r}")
            continue
        severity = advisory.get("severity")
        findings = advisory.get("findings")
        if severity != "high" or not isinstance(findings, list) or not findings:
            errors.add(f"invalid {_ALLOWED_GHSA} severity/findings")
            continue
        observed[severity] += len(findings)
        for finding in findings:
            if not isinstance(finding, dict) or not isinstance(finding.get("paths"), list) or not finding["paths"]:
                errors.add(f"invalid {_ALLOWED_GHSA} finding: {finding!r}")
                continue
            for path in finding["paths"]:
                errors.update(_path_errors(path, finding.get("version"), package_json))

    for severity in observed:
        count = vulnerabilities.get(severity)
        if not isinstance(count, int) or count != observed[severity]:
            errors.add(f"pnpm audit {severity} count mismatch: report={count!r}, details={observed[severity]}")
    return sorted(errors)


def main() -> int:
    try:
        report = json.load(sys.stdin)
        package_json = json.loads((Path(__file__).resolve().parents[1] / "web/package.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(f"unable to read dependency audit inputs: {exc}", file=sys.stderr)
        return 1

    if not isinstance(report, dict) or not isinstance(package_json, dict):
        print("dependency audit inputs must be JSON objects", file=sys.stderr)
        return 1
    errors = audit_policy_errors(report, package_json)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if report.get("advisories"):
        print(f"pnpm audit: allowed tooling-only advisory {_ALLOWED_GHSA}")
    else:
        print("pnpm audit: no high-severity advisories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
