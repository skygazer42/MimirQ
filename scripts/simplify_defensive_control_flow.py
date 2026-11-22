"""Find redundant control flow across every project file.

Edits are limited to equivalent nested conditions and else blocks after a direct
terminating statement. Cached-value reparsing is reported for call-chain review.
"""

import argparse
import ast
import hashlib
import io
import json
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.audit_defensive_code import file_kind, inventory

TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


class CanonicalFlow(ast.NodeTransformer):
    """Canonical AST used to reject source edits that change program meaning."""

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.BoolOp:
        self.generic_visit(node)
        node.values = [
            value
            for item in node.values
            for value in (item.values if isinstance(item, ast.BoolOp) and type(item.op) is type(node.op) else [item])
        ]
        return node

    def visit_If(self, node: ast.If) -> ast.If | list[ast.stmt]:
        self.generic_visit(node)
        while not node.orelse and len(node.body) == 1 and isinstance(node.body[0], ast.If) and not node.body[0].orelse:
            child = node.body[0]
            node.test = self.visit_BoolOp(ast.BoolOp(op=ast.And(), values=[node.test, child.test]))
            node.body = child.body
        if node.orelse and node.body and isinstance(node.body[-1], TERMINATORS):
            otherwise = node.orelse
            node.orelse = []
            return [node, *otherwise]
        return node


def canonical(source: str) -> str:
    tree = CanonicalFlow().visit(ast.parse(source))
    return ast.dump(tree, include_attributes=False)


def indentation(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def dedent_lines(
    lines: list[str], outer_indent: str, amount: str, *, start_line: int, literal_lines: set[int]
) -> list[str]:
    prefix = outer_indent + amount
    return [
        outer_indent + line[len(prefix) :] if line.startswith(prefix) and number not in literal_lines else line
        for number, line in enumerate(lines, start_line)
    ]


def source_conditions(node: ast.If, source: str) -> str:
    text = ast.get_source_segment(source, node.test)
    if isinstance(node.test, (ast.NamedExpr, ast.IfExp, ast.Lambda)) or (
        isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.Or)
    ):
        return f"({text})"
    return text


def inspect_python(source: str, *, apply: bool = False) -> tuple[str, list[dict[str, Any]], int]:
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    literal_lines = {
        number
        for token in tokens
        if token.type == tokenize.STRING
        for number in range(token.start[0] + 1, token.end[0] + 1)
    }
    comments = {token.start[0]: token.string for token in tokens if token.type == tokenize.COMMENT}
    endings = "\r\n" if "\r\n" in source else "\n"
    findings: list[dict[str, Any]] = []
    edits: list[tuple[int, int, str]] = []

    def header_supported(node: ast.If) -> bool:
        return (
            node.test.lineno == node.lineno == node.test.end_lineno
            and node.body[0].lineno > node.lineno
            and not any(marker in comments.get(node.lineno, "").lower() for marker in ("noqa", "type:", "pragma"))
            and lines[node.lineno - 1].lstrip().startswith("if ")
        )

    def independent_if(node: ast.If) -> bool:
        if lines[node.lineno - 1].lstrip().startswith("if "):
            return True
        parent = parents.get(node)
        return (
            lines[node.lineno - 1].lstrip().startswith("elif ")
            and isinstance(parent, ast.If)
            and parent.orelse == [node]
            and bool(parent.body)
            and isinstance(parent.body[-1], TERMINATORS)
            and independent_if(parent)
        )

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and not node.orelse
            and len(node.body) == 1
            and isinstance(node.body[0], ast.If)
            and not node.body[0].orelse
        ):
            chain = [node]
            while (
                not chain[-1].orelse
                and len(chain[-1].body) == 1
                and isinstance(chain[-1].body[0], ast.If)
                and not chain[-1].body[0].orelse
            ):
                chain.append(chain[-1].body[0])
            safe = all(header_supported(item) for item in chain)
            findings.append(
                {
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "rule": "nested-if-chain",
                    "safe_fix": safe,
                    "depth": len(chain),
                    "reason": "Sequential condition checks have no else branch; short-circuit conjunction preserves evaluation order."
                    if safe
                    else "A source pragma or inline/multiline conditional header requires source-specific review.",
                }
            )
            if safe:
                outer = indentation(lines[node.lineno - 1])
                inner = indentation(lines[chain[-1].lineno - 1])
                retained_comments = [
                    outer + comments[item.lineno] + endings for item in chain if item.lineno in comments
                ]
                body_comments = []
                for parent, child in zip(chain, chain[1:], strict=False):
                    body_comments.extend(
                        outer + "    " + line.lstrip(" \t")
                        for line in lines[parent.lineno : child.lineno - 1]
                        if line.strip()
                    )
                condition = " and ".join(source_conditions(item, source) for item in chain)
                body = dedent_lines(
                    lines[chain[-1].lineno : node.end_lineno],
                    outer,
                    inner[len(outer) :],
                    start_line=chain[-1].lineno + 1,
                    literal_lines=literal_lines,
                )
                replacement = (
                    "".join(retained_comments) + outer + f"if {condition}:" + endings + "".join(body_comments + body)
                )
                edits.append((node.lineno - 1, node.end_lineno, replacement))
        if isinstance(node, ast.If) and node.orelse and node.body and isinstance(node.body[-1], TERMINATORS):
            outer = indentation(lines[node.lineno - 1])
            following = node.orelse[0].lineno - 1
            if independent_if(node) and lines[following].startswith(outer + "elif "):
                findings.append(
                    {
                        "line": node.lineno,
                        "end_line": following + 1,
                        "rule": "elif-after-terminator",
                        "safe_fix": True,
                        "reason": "The preceding if exits; elif becomes an independent following if without moving its body.",
                    }
                )
                edits.append((following, following + 1, outer + "if " + lines[following][len(outer + "elif ") :]))
            else_lines = [
                index
                for index in range(node.body[-1].end_lineno, node.orelse[0].lineno)
                if lines[index].startswith(outer + "else:")
            ]
            safe = len(else_lines) == 1 and independent_if(node) and node.orelse[0].lineno > else_lines[0] + 1
            findings.append(
                {
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "rule": "else-after-terminator",
                    "safe_fix": safe,
                    "reason": "The preceding branch exits; following statements can remain at the enclosing indentation."
                    if safe
                    else "An elif belonging to a non-terminating outer branch or inline else requires source-specific review.",
                }
            )
            if safe:
                header = else_lines[0]
                inner = indentation(lines[node.orelse[0].lineno - 1])
                comment = lines[header].split("#", 1)
                retained_comment = outer + "#" + comment[1] if len(comment) == 2 else ""
                body = dedent_lines(
                    lines[header + 1 : node.end_lineno],
                    outer,
                    inner[len(outer) :],
                    start_line=header + 2,
                    literal_lines=literal_lines,
                )
                edits.append((header, node.end_lineno, retained_comment + "".join(body)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            reparses = [
                item
                for item in ast.walk(node)
                if isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id in {"UUID", "int", "float", "str"}
            ]
            has_try = any(isinstance(item, ast.Try) for item in ast.walk(node))
            has_type_check = any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id in {"isinstance", "hasattr", "getattr"}
                for item in ast.walk(node)
            )
            if reparses and has_try and has_type_check:
                findings.append(
                    {
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                        "rule": "guarded-reparse-review",
                        "function": node.name,
                        "safe_fix": False,
                        "reason": "Trace value writers and declared types: internal values should not be repeatedly reparsed or silently discarded.",
                    }
                )
    selected = []
    # Outer rewrites subsume nested rewrites on this pass; subsequent passes
    # expose any remaining independent opportunities.
    for edit in sorted(set(edits), key=lambda item: (item[0], -item[1])):
        if selected and edit[0] < selected[-1][1]:
            continue
        selected.append(edit)
    result = source
    if apply and selected:
        for start, end, replacement in reversed(selected):
            lines[start:end] = [replacement]
        result = "".join(lines)
        if canonical(result) != canonical(source):
            raise ValueError("Control-flow canonical AST changed; refusing source rewrite")
    return result, findings, len(selected)


def run(root: Path, output: Path, scopes: list[str], apply: bool, backup: Path | None) -> dict[str, Any]:
    records = []
    changed = []
    for relative in inventory(root):
        path = root / relative
        raw = path.read_bytes()
        record: dict[str, Any] = {
            "file": relative,
            "kind": file_kind(relative),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "findings": [],
        }
        if path.suffix == ".py":
            source = raw.decode("utf-8-sig")
            eligible = (
                any(relative == scope or relative.startswith(scope.rstrip("/") + "/") for scope in scopes)
                if scopes
                else False
            )
            # Always prove candidate source rewrites against the canonical AST,
            # even during a read-only whole-project scan.
            candidate, findings, edits = inspect_python(source, apply=True)
            updated = candidate if apply and eligible else source
            record.update(status="python-control-flow-ast-inspected", findings=findings, automatic_edits=edits)
            if updated != source:
                if path.read_bytes() != raw:
                    raise RuntimeError(f"Concurrent edit: {relative}")
                if backup:
                    destination = backup / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        destination.write_bytes(raw)
                prefix = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
                path.write_bytes(prefix + updated.encode("utf-8"))
                changed.append({"file": relative, "edits": edits})
        else:
            record.update(
                status="other-language-or-resource-indexed",
                reason="Frontend compiler report or non-executable resource classification applies.",
            )
        records.append(record)
    report = {
        "files": len(records),
        "changed": changed,
        "rules": dict(Counter(item["rule"] for record in records for item in record["findings"])),
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    report = run(args.root, args.output, args.scope, args.apply, args.backup)
    print(json.dumps({key: value for key, value in report.items() if key != "records"}))


if __name__ == "__main__":
    main()
