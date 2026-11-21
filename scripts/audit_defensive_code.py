"""Inventory every project file and audit Python defensive code using AST evidence.

Only declared, directly imported Settings fields and identity primitive casts are
eligible for automatic edits. Input coercion and exception policies are reported
for call-chain review, not deleted by a text replacement.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

PRIMITIVES = {"str", "int", "float", "bool"}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".mts",
    ".jsx",
    ".html",
    ".md",
    ".mdx",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".css",
    ".scss",
    ".svg",
    ".sql",
    ".sh",
    ".ps1",
    ".mk",
    ".tpl",
    ".mako",
    ".http",
    ".example",
    ".prod",
}


def inventory(root: Path) -> list[str]:
    root = root.resolve()
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    files: set[str] = set()
    for name in result.stdout.decode("utf-8").split("\0"):
        path = root / name
        if name and path.is_file() and path.resolve() == path:
            files.add(name)
    return sorted(files)


def annotation_type(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name) and node.id in PRIMITIVES:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return annotation_type(ast.parse(node.value, mode="eval").body)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
        values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in values):
            return "str"
    return None


def settings_contract(root: Path) -> tuple[dict[str, str | None], set[str]]:
    tree = ast.parse((root / "app/infrastructure/config.py").read_text(encoding="utf-8-sig"))
    model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    fields: dict[str, str | None] = {}
    always_truthy: set[str] = set()
    for node in model.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        fields[node.target.id] = annotation_type(node.annotation)
        annotation = node.annotation
        if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
            values = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            if annotation.value.id == "Literal" and all(
                isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value for value in values
            ):
                always_truthy.add(node.target.id)
    return fields, always_truthy


def pure_default(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError):
        return False
    return True


def scope_bindings(nodes: list[ast.stmt], *, module: bool = False) -> set[str]:
    """Collect bindings in one lexical scope, without leaking nested scopes."""
    names: set[str] = set()

    class Bindings(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)

        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            names.add(node.name)

        visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            names.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_Import(self, node: ast.Import) -> None:
            names.update(item.asname or item.name.split(".")[0] for item in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            names.update(
                item.asname or item.name
                for item in node.names
                if not (module and node.module == "app.infrastructure.config" and item.name == "settings")
            )

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name:
                names.add(node.name)
            self.generic_visit(node)

        def visit_comprehension(self, node: ast.comprehension) -> None:
            # Iteration targets belong to the comprehension scope, not its parent.
            self.visit(node.iter)
            for condition in node.ifs:
                self.visit(condition)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name:
                names.add(node.name)
            self.generic_visit(node)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name:
                names.add(node.name)

    visitor = Bindings()
    for node in nodes:
        visitor.visit(node)
    return names


class PythonAudit(ast.NodeVisitor):
    def __init__(
        self, source: str, fields: dict[str, str | None], truthy: set[str], *, narrow_errors: bool = False
    ) -> None:
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.fields = fields
        self.truthy = truthy
        self.tree = ast.parse(source)
        self.aliases = {
            item.asname or item.name
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "app.infrastructure.config"
            for item in node.names
            if item.name == "settings"
        }
        # Conditional/loop bindings also invalidate a module alias.
        module_bound = scope_bindings(self.tree.body, module=True)
        global_rebindings = {
            name for node in ast.walk(self.tree) if isinstance(node, ast.Global) for name in node.names
        }
        module_bound.update(global_rebindings)
        module_bound.update(
            item.target.id
            for item in ast.walk(self.tree)
            if isinstance(item, ast.NamedExpr) and isinstance(item.target, ast.Name)
        )
        self.aliases.difference_update(module_bound)
        self.shadowed: list[set[str]] = [module_bound - self.aliases]
        self.function = "<module>"
        self.findings: list[dict[str, Any]] = []
        self.patches: list[tuple[int, int, str]] = []
        self.narrow_errors = narrow_errors

    def offset(self, line: int, byte_column: int) -> int:
        prefix = self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8")
        return self.starts[line - 1] + len(prefix)

    def span(self, node: ast.AST) -> tuple[int, int]:
        return self.offset(node.lineno, node.col_offset), self.offset(node.end_lineno, node.end_col_offset)

    def text(self, node: ast.AST) -> str:
        start, end = self.span(node)
        return self.source[start:end]

    def settings_field(self, node: ast.expr) -> str | None:
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.aliases
            and not any(node.value.id in scope for scope in self.shadowed)
        ):
            return node.attr if node.attr in self.fields else None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and not any("getattr" in scope for scope in self.shadowed)
            and len(node.args) in {2, 3}
            and not node.keywords
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in self.aliases
            and not any(node.args[0].id in scope for scope in self.shadowed)
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in self.fields
            and (len(node.args) == 2 or pure_default(node.args[2]))
        ):
            return node.args[1].value
        return None

    def primitive(self, node: ast.expr) -> str | None:
        field = self.settings_field(node)
        if field is not None:
            return self.fields[field]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in PRIMITIVES
            and len(node.args) == 1
            and not node.keywords
            and not any(node.func.id in scope for scope in self.shadowed)
        ):
            return node.func.id
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            kinds = [
                self.primitive(value) if not isinstance(value, ast.Constant) else type(value.value).__name__
                for value in node.values
            ]
            if len(set(kinds)) == 1:
                return kinds[0]
        return None

    def settings_provenance(self, node: ast.expr) -> bool:
        if self.settings_field(node) is not None:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PRIMITIVES:
            return len(node.args) == 1 and self.settings_provenance(node.args[0])
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return self.settings_provenance(node.values[0]) and all(pure_default(item) for item in node.values[1:])
        return False

    def rewrite(self, node: ast.expr) -> tuple[str, str] | None:
        if isinstance(node, ast.Call):
            field = self.settings_field(node)
            if field is not None and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                return f"{node.args[0].id}.{field}", "typed-settings-getattr"
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in PRIMITIVES
                and len(node.args) == 1
                and not node.keywords
                and not any(node.func.id in scope for scope in self.shadowed)
                and self.primitive(node.args[0]) == node.func.id
                and (node.func.id != "str" or self.settings_provenance(node.args[0]))
                # Preserve explicit int-to-float serialization and float field defaults.
                and (
                    node.func.id != "float"
                    or (
                        isinstance(node.args[0], ast.Call)
                        and isinstance(node.args[0].func, ast.Name)
                        and node.args[0].func.id == "float"
                    )
                )
            ):
                text = self.render(node.args[0])
                expression = ast.parse(f"({text}\n)", mode="eval").body
                if isinstance(expression, (ast.BoolOp, ast.BinOp, ast.Compare, ast.IfExp, ast.NamedExpr, ast.Lambda)):
                    text = f"({text})"
                return text, "identity-primitive-cast"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
            left, default = node.values
            field = self.settings_field(left)
            if field is not None and (
                field in self.truthy
                or (
                    isinstance(default, ast.Constant)
                    and (
                        (self.fields[field] == "str" and default.value == "")
                        or (self.fields[field] == "int" and type(default.value) is int and default.value == 0)
                        or (self.fields[field] == "bool" and default.value is False)
                    )
                )
            ):
                return self.render(left), "neutral-settings-default"
        return None

    def render(self, node: ast.expr) -> str:
        # Nested scopes must be visited with their own bindings, never recursively
        # rewritten while rendering an enclosing expression.
        if any(
            isinstance(item, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.NamedExpr))
            for item in ast.walk(node)
        ):
            return self.text(node)
        replacement = self.rewrite(node)
        if replacement:
            return replacement[0]
        start, _end = self.span(node)
        text = self.text(node)
        edits = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                before = self.text(child)
                after = self.render(child)
                if before != after:
                    child_start, child_end = self.span(child)
                    edits.append((child_start - start, child_end - start, after))
        for left, right, value in sorted(edits, reverse=True):
            text = text[:left] + value + text[right:]
        return text

    def add(self, node: ast.AST, rule: str, reason: str, *, safe: bool = False) -> None:
        self.findings.append(
            {
                "line": node.lineno,
                "end_line": node.end_lineno,
                "rule": rule,
                "function": self.function,
                "safe_fix": safe,
                "reason": reason,
                "excerpt": self.text(node).replace("\n", " ").replace("\r", " ")[:180],
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        old_function = self.function
        self.function = node.name
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
        local = {arg.arg for arg in args} | scope_bindings(node.body)
        self.shadowed.append(local)
        if node.name.startswith(("_coerce_", "coerce_", "_safe_", "safe_", "_as_", "as_")):
            conversions = [
                item
                for item in ast.walk(node)
                if isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id in PRIMITIVES | {"UUID"}
            ]
            if conversions:
                self.add(
                    node,
                    "coercion-helper",
                    "Trace callers: boundary parsing may be required; internal typed data should not be re-coerced.",
                )
        self.generic_visit(node)
        self.shadowed.pop()
        self.function = old_function

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
        self.shadowed.append({arg.arg for arg in args})
        self.generic_visit(node)
        self.shadowed.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.shadowed.append(scope_bindings(node.body))
        self.generic_visit(node)
        self.shadowed.pop()

    def comprehension(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        self.visit(node.generators[0].iter)
        bound = {
            item.id
            for generator in node.generators
            for item in ast.walk(generator.target)
            if isinstance(item, ast.Name)
        }
        self.shadowed.append(bound)
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for value in [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]:
            self.visit(value)
        self.shadowed.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.comprehension(node)

    def visit_Call(self, node: ast.Call) -> None:
        scope_sensitive = any(
            isinstance(item, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.NamedExpr))
            for item in ast.walk(node)
        )
        replacement = None if scope_sensitive else self.rewrite(node)
        if replacement:
            text, rule = replacement
            self.add(
                node,
                rule,
                "Declared Settings field or identity conversion; no unknown-input fallback is removed.",
                safe=True,
            )
            self.patches.append((*self.span(node), text))
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in self.aliases | {"settings"}
        ):
            self.add(
                node,
                "dynamic-settings-read",
                "Field, fallback expression, or scope is not proven safe for automatic replacement.",
            )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        scope_sensitive = any(
            isinstance(item, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.NamedExpr))
            for item in ast.walk(node)
        )
        replacement = None if scope_sensitive else self.rewrite(node)
        if replacement:
            self.add(
                node,
                replacement[1],
                "Fallback is neutral for the declared Settings type or the Literal is always nonempty.",
                safe=True,
            )
            self.patches.append((*self.span(node), replacement[0]))
        elif isinstance(node.op, ast.Or):
            for value in node.values[1:]:
                if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.Constant)):
                    self.add(
                        node,
                        "falsey-default",
                        "Review domain absence/zero semantics and input provenance before changing.",
                    )
                    break
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        broad = node.type is None or any(
            isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"} for item in ast.walk(node.type)
        )
        if broad:
            raises = any(isinstance(item, ast.Raise) for body in node.body for item in ast.walk(body))
            returns = any(
                isinstance(item, (ast.Return, ast.Continue, ast.Pass)) for body in node.body for item in ast.walk(body)
            )
            self.add(
                node,
                "broad-exception-propagates"
                if raises
                else "broad-exception-fallback"
                if returns
                else "broad-exception-handling",
                "Inspect exception policy: explicit propagation, supported optional degradation, or unexpected failure suppression.",
            )
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        calls = [item for stmt in node.body for item in ast.walk(stmt) if isinstance(item, ast.Call)]
        numeric = any(isinstance(call.func, ast.Name) and call.func.id in {"int", "float", "UUID"} for call in calls)

        def conversion_call(call: ast.Call) -> bool:
            if isinstance(call.func, ast.Name):
                return call.func.id in PRIMITIVES | {"UUID", "isinstance"} and not any(
                    call.func.id in scope for scope in self.shadowed
                )
            if isinstance(call.func, ast.Attribute) and call.func.attr in {"strip", "lower", "upper"}:
                receiver = call.func.value
                return self.settings_field(receiver) is not None or (
                    isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "str"
                )
            return False

        property_access = any(
            isinstance(item, ast.Attribute)
            and self.settings_field(item) is None
            and item.attr not in {"strip", "lower", "upper"}
            for stmt in node.body
            for item in ast.walk(stmt)
        )
        index_access = any(
            isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Load)
            for stmt in node.body
            for item in ast.walk(stmt)
        )
        if (
            numeric
            and all(conversion_call(call) for call in calls)
            and not property_access
            and not index_access
            and not any(
                isinstance(item, (ast.Await, ast.Yield, ast.YieldFrom, ast.Raise))
                for stmt in node.body
                for item in ast.walk(stmt)
            )
        ):
            uuid_calls = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "UUID"]
            uuid_text_only = bool(uuid_calls) and all(
                len(call.args) == 1
                and isinstance(call.args[0], ast.Call)
                and isinstance(call.args[0].func, ast.Name)
                and call.args[0].func.id == "str"
                for call in uuid_calls
            )
            exception_text = (
                "ValueError"
                if uuid_text_only
                and not any(isinstance(call.func, ast.Name) and call.func.id in {"int", "float"} for call in calls)
                else "(TypeError, ValueError, OverflowError)"
            )
            for handler in node.handlers:
                if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                    self.add(
                        handler,
                        "primitive-conversion-exception",
                        "Try body contains only primitive parsing; review the failure policy before enabling exception narrowing.",
                    )
                    if self.narrow_errors:
                        self.patches.append((*self.span(handler.type), exception_text))
        self.generic_visit(node)

    def analyze(self) -> tuple[list[dict[str, Any]], str, int]:
        self.visit(self.tree)
        # Outermost semantic rewrites include their nested rewrites.
        selected: list[tuple[int, int, str]] = []
        for patch in sorted(set(self.patches), key=lambda item: (item[0], -item[1])):
            if selected and patch[0] < selected[-1][1]:
                continue
            selected.append(patch)
        result = self.source
        for start, end, text in reversed(selected):
            result = result[:start] + text + result[end:]
        ast.parse(result)
        return self.findings, result, len(selected)


def file_kind(name: str) -> str:
    if name.startswith(("tests/", "web/e2e/")) or ".test." in name or ".spec." in name:
        return "test"
    if name.startswith(("scripts/", "ci/", "web/scripts/")):
        return "tooling"
    if name.startswith(("docs/", "docs-site/docs/", "docs-site/i18n/")) or Path(name).suffix in {".md", ".mdx"}:
        return "documentation"
    if name.startswith(("web/public/", "docs-site/static/")):
        return "static-asset"
    if Path(name).suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts"}:
        return "runtime-source"
    return "configuration-or-asset"


def scan(
    root: Path, scopes: list[str], apply: bool, backup: Path | None, *, narrow_errors: bool = False
) -> dict[str, Any]:
    fields, truthy = settings_contract(root)
    records = []
    changed = []
    totals: Counter[str] = Counter()
    for name in inventory(root):
        path = root / name
        data = path.read_bytes()
        record: dict[str, Any] = {
            "file": name,
            "kind": file_kind(name),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "findings": [],
        }
        eligible = not scopes or any(name == scope or name.startswith(scope.rstrip("/") + "/") for scope in scopes)
        if path.suffix.lower() == ".py":
            try:
                source = data.decode("utf-8-sig")
                audit = PythonAudit(source, fields, truthy, narrow_errors=narrow_errors)
                findings, rewritten, edits = audit.analyze()
                record.update(status="python-ast-inspected", findings=findings, safe_edits=edits)
                totals.update(item["rule"] for item in findings)
                if apply and eligible and rewritten != source:
                    if path.read_bytes() != data:
                        raise RuntimeError(f"Concurrent change: {name}")
                    if backup is not None:
                        destination = backup / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if not destination.exists():
                            destination.write_bytes(data)
                    prefix = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
                    path.write_bytes(prefix + rewritten.encode("utf-8"))
                    record["action"] = "safe-rewrite-applied"
                    changed.append({"file": name, "edits": edits})
            except (SyntaxError, UnicodeDecodeError) as exc:
                record.update(status="parse-error", error=str(exc))
        elif path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts"}:
            record.update(
                status="javascript-inventory",
                reason="Compiler AST/typechecker review is supplied by the frontend scanner.",
            )
        elif path.suffix.lower() in TEXT_SUFFIXES or not path.suffix:
            record.update(
                status="non-python-text-indexed",
                reason="Not executed as Python; examples, config, styles and markup require their own boundary.",
            )
        else:
            record.update(status="non-code-asset", reason="Binary or data asset; defensive code rules do not apply.")
        records.append(record)
    return {
        "root": str(root),
        "files": len(records),
        "python_files": sum(Path(item["file"]).suffix == ".py" for item in records),
        "rules": dict(totals),
        "changed": changed,
        "parse_errors": [item["file"] for item in records if item["status"] == "parse-error"],
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--apply-safe", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--narrow-primitive-errors", action="store_true")
    args = parser.parse_args()
    report = scan(
        args.root.resolve(), args.scope, args.apply_safe, args.backup, narrow_errors=args.narrow_primitive_errors
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
