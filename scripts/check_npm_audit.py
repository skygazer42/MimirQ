"""Permit only the unfixed image-size advisory on Docusaurus' build path."""

import json
import sys
from pathlib import Path
from typing import Any

_ALLOWED_ADVISORY_URLS = {
    "https://github.com/advisories/GHSA-5p2g-fcmc-qvqq",
    "https://github.com/advisories/GHSA-w3rx-r6r6-pgpr",
}
_IMAGE_SIZE_VERSION = "2.0.2"
_MDX_LOADER_PATH = "node_modules/@docusaurus/mdx-loader"
_IMAGE_SIZE_PATH = "node_modules/image-size"


def _package_scope_errors(package_json: dict[str, Any]) -> set[str]:
    errors: set[str] = set()
    for section_name in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        section = package_json.get(section_name, {})
        if not isinstance(section, dict):
            errors.add(f"invalid docs package section: {section_name}")
        elif "image-size" in section:
            errors.add(f"image-size must not be a direct docs dependency: {section_name}")
    return errors


def _lock_entry_errors(packages: dict[str, Any]) -> set[str]:
    errors: set[str] = set()
    image_size = packages.get(_IMAGE_SIZE_PATH)
    if not isinstance(image_size, dict) or image_size.get("version") != _IMAGE_SIZE_VERSION:
        errors.add(f"unexpected image-size lock entry: {image_size!r}")

    mdx_loader = packages.get(_MDX_LOADER_PATH)
    if not isinstance(mdx_loader, dict):
        errors.add(f"missing Docusaurus MDX loader lock entry: {mdx_loader!r}")
        return errors

    dependencies = mdx_loader.get("dependencies")
    if not isinstance(dependencies, dict) or dependencies.get("image-size") != "^2.0.2":
        errors.add(f"unexpected Docusaurus image-size dependency: {dependencies!r}")
    return errors


def _image_size_dependency_parents(packages: dict[str, Any]) -> list[str]:
    parents: list[str] = []
    for path, package in packages.items():
        if not isinstance(path, str) or not isinstance(package, dict):
            continue
        dependencies = package.get("dependencies", {})
        if isinstance(dependencies, dict) and "image-size" in dependencies:
            parents.append(path)
    return parents


def _lock_scope_errors(package_json: dict[str, Any], package_lock: dict[str, Any]) -> set[str]:
    errors = _package_scope_errors(package_json)

    packages = package_lock.get("packages")
    if not isinstance(packages, dict):
        return errors | {"invalid docs package-lock packages"}

    errors.update(_lock_entry_errors(packages))
    parents = _image_size_dependency_parents(packages)
    if parents != [_MDX_LOADER_PATH]:
        errors.add(f"unexpected image-size dependency parents: {parents!r}")
    return errors


def _audit_sections(report: dict[str, Any], errors: set[str]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    metadata = report.get("metadata")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(metadata, dict) or not isinstance(vulnerabilities, dict):
        errors.add("invalid or incomplete npm audit response")
        return None

    counts = metadata.get("vulnerabilities")
    if not isinstance(counts, dict):
        errors.add("invalid npm audit vulnerability summary")
        return None
    return counts, vulnerabilities


def _severe_vulnerabilities(vulnerabilities: dict[str, Any], errors: set[str]) -> dict[str, dict[str, Any]]:
    severe: dict[str, dict[str, Any]] = {}
    for package, vulnerability in vulnerabilities.items():
        if not isinstance(package, str) or not isinstance(vulnerability, dict):
            errors.add(f"invalid npm audit vulnerability: {package!r}={vulnerability!r}")
            continue
        if vulnerability.get("severity") in {"high", "critical"}:
            severe[package] = vulnerability
    return severe


def _validate_severe_count(counts: dict[str, Any], severe: dict[str, dict[str, Any]], errors: set[str]) -> None:
    high = counts.get("high")
    critical = counts.get("critical")
    if isinstance(high, int) and isinstance(critical, int) and high + critical == len(severe):
        return
    errors.add(f"npm audit severe count mismatch: report=high:{high!r}/critical:{critical!r}, details={len(severe)}")


def _validated_advisory_url(advisory: dict[str, Any], errors: set[str]) -> str | None:
    url = advisory.get("url")
    if (
        advisory.get("name") == "image-size"
        and advisory.get("dependency") == "image-size"
        and advisory.get("severity") == "high"
        and advisory.get("range") == "<=2.0.2"
        and url in _ALLOWED_ADVISORY_URLS
    ):
        return url if isinstance(url, str) else None
    errors.add(f"unexpected image-size advisory: {advisory!r}")
    return None


def _validate_direct_severe_package(
    package: str,
    vulnerability: dict[str, Any],
    errors: set[str],
) -> tuple[set[str], bool]:
    nodes = vulnerability.get("nodes")
    if nodes != [f"node_modules/{package}"]:
        errors.add(f"unexpected npm audit nodes for {package}: {nodes!r}")

    via = vulnerability.get("via")
    if not isinstance(via, list) or not via:
        errors.add(f"invalid npm audit path for {package}: {via!r}")
        return set(), False

    direct = [entry for entry in via if isinstance(entry, dict)]
    if not direct:
        return set(), False
    if package != "image-size" or len(direct) != len(via):
        errors.add(f"unexpected direct high/critical advisory: {package} {direct!r}")
        return set(), False
    if vulnerability.get("fixAvailable") is not False:
        errors.add(f"image-size unexpectedly has a fix: {vulnerability.get('fixAvailable')!r}")

    urls = {_validated_advisory_url(advisory, errors) for advisory in direct}
    urls.discard(None)
    return urls, True


def _collect_direct_allowances(severe: dict[str, dict[str, Any]], errors: set[str]) -> tuple[set[str], set[str]]:
    allowed_advisories: set[str] = set()
    allowed_packages: set[str] = set()
    for package, vulnerability in severe.items():
        urls, package_allowed = _validate_direct_severe_package(package, vulnerability, errors)
        allowed_advisories.update(urls)
        if package_allowed:
            allowed_packages.add(package)
    return allowed_advisories, allowed_packages


def _is_allowed_propagation(vulnerability: dict[str, Any], allowed_packages: set[str]) -> bool:
    via = vulnerability.get("via")
    return bool(
        isinstance(via, list) and via and all(isinstance(parent, str) and parent in allowed_packages for parent in via)
    )


def _pending_unallowed_packages(severe: dict[str, dict[str, Any]], allowed_packages: set[str]) -> set[str]:
    pending = set(severe) - allowed_packages
    while pending:
        newly_allowed = {package for package in pending if _is_allowed_propagation(severe[package], allowed_packages)}
        if not newly_allowed:
            break
        allowed_packages.update(newly_allowed)
        pending.difference_update(newly_allowed)
    return pending


def audit_policy_errors(
    report: dict[str, Any],
    package_json: dict[str, Any],
    package_lock: dict[str, Any],
) -> list[str]:
    errors = _lock_scope_errors(package_json, package_lock)
    sections = _audit_sections(report, errors)
    if sections is None:
        return sorted(errors)

    counts, vulnerabilities = sections
    severe = _severe_vulnerabilities(vulnerabilities, errors)
    _validate_severe_count(counts, severe, errors)
    allowed_advisories, allowed_packages = _collect_direct_allowances(severe, errors)

    if allowed_advisories != _ALLOWED_ADVISORY_URLS:
        errors.add(f"unexpected allowed image-size advisories: {sorted(allowed_advisories)!r}")

    pending = _pending_unallowed_packages(severe, allowed_packages)
    for package in sorted(pending):
        errors.add(f"unexpected high/critical advisory path for {package}: {severe[package].get('via')!r}")
    return sorted(errors)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        report = json.load(sys.stdin)
        package_json = json.loads((root / "docs-site/package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((root / "docs-site/package-lock.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(f"unable to read dependency audit inputs: {exc}", file=sys.stderr)
        return 1

    if not all(isinstance(item, dict) for item in (report, package_json, package_lock)):
        print("dependency audit inputs must be JSON objects", file=sys.stderr)
        return 1
    errors = audit_policy_errors(report, package_json, package_lock)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("npm audit: allowed unfixed image-size advisories on Docusaurus' local build path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
