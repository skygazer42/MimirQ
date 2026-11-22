"""Check runtime business dependencies without importing application modules.

The explicit migration baseline is a ratchet, not a wildcard allowlist: removed
edges must be removed from it and new edges fail even inside a legacy file.
"""

import argparse
import ast
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    rule: str
    scope: str
    target: str

    def identity(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in ("file", "rule", "scope", "target")}


class RuntimeDependencies(ast.NodeVisitor):
    def __init__(self, module: str, routers: set[str]):
        self.module = module
        self.routers = routers
        self.router_names = sorted(routers, key=len, reverse=True)
        self.aliases: dict[str, str] = {}
        self.constants: dict[str, str] = {}
        self.scope: list[str] = []
        self.violations: list[Violation] = []
        self.router_only_names: set[str] = set()

    def visit_Module(self, node: ast.Module) -> None:
        parents = {child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)}
        uses: dict[str, list[ast.Name]] = {}
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                uses.setdefault(child.id, []).append(child)
        self.router_only_names = {
            name
            for name, references in uses.items()
            if all(isinstance(parents[ref], ast.Attribute) and parents[ref].attr == "router" for ref in references)
        }
        self.generic_visit(node)

    def qualified(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{self.qualified(node.value)}.{node.attr}"
        return ""

    def add(self, node: ast.AST, rule: str, target: str) -> None:
        self.violations.append(
            Violation(self.module.replace(".", "/") + ".py", node.lineno, rule, ".".join(self.scope), target)
        )

    def dependency(self, node: ast.AST, target: str, *, router_only: bool = False) -> None:
        router = next(
            (name for name in self.router_names if target == name or target.startswith(name + ".")),
            None,
        )
        if router is None:
            return
        # The application and API assemblers may mount routers. Business calls
        # remain checked, including calls made during application startup.
        if router_only and (self.module.startswith("app.api.") or self.module == "app.main"):
            return
        if self.module in {"app.api.v1", "app.api.v1.router"} and target == router:
            return
        self.add(node, "api-assembler", router)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            self.dependency(
                node, alias.name, router_only=(alias.asname or alias.name.split(".")[0]) in self.router_only_names
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            package = self.module.split(".")[:-1]
            base = ".".join(package[: len(package) - node.level + 1] + ([base] if base else []))
        for alias in node.names:
            target = f"{base}.{alias.name}"
            self.aliases[alias.asname or alias.name] = target
            self.dependency(
                node,
                target,
                router_only=alias.name == "router" or (alias.asname or alias.name) in self.router_only_names,
            )

    def visit_If(self, node: ast.If) -> None:
        # TYPE_CHECKING is false at runtime; its else branch still executes.
        test = node.test
        negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
        guard = test.operand if negated else test
        if self.qualified(guard) == "typing.TYPE_CHECKING":
            for statement in node.body if negated else node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.constants[target.id] = node.value.value
        self.generic_visit(node)

    def string_value(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.constants.get(node.id)
        return None

    def visit_Call(self, node: ast.Call) -> None:
        if self.qualified(node.func) in {"importlib.import_module", "__import__", "sys.modules.get"} and node.args:
            target = self.string_value(node.args[0])
            if target is not None:
                self.dependency(node, target)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self.qualified(node.value) == "sys.modules":
            target = self.string_value(node.slice)
            if target is not None:
                self.dependency(node, target)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Also reject access through an imported API package alias.
        target = self.qualified(node)
        if target in self.routers and self.qualified(node.value) not in self.routers:
            self.dependency(node, target)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        if node.annotation is not None and self.qualified(node.annotation) in {"typing.Any", "Any"}:
            if node.arg.endswith("_module") or node.arg in {"module", "docs_mod", "service"}:
                self.add(node, "opaque-owner", node.arg)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        aliases, constants = self.aliases.copy(), self.constants.copy()
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self.aliases.pop(argument.arg, None)
            self.constants.pop(argument.arg, None)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
        self.aliases, self.constants = aliases, constants

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        aliases, constants = self.aliases.copy(), self.constants.copy()
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
        self.aliases, self.constants = aliases, constants


def inspect_source(source: str, module: str, routers: set[str]) -> list[Violation]:
    visitor = RuntimeDependencies(module, routers)
    visitor.visit(ast.parse(source))
    return visitor.violations


def scan_repository(root: Path) -> list[Violation]:
    sources = {
        path: ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for path in sorted((root / "app").rglob("*.py"))
    }
    modules = {
        path: ".".join(path.relative_to(root).with_suffix("").parts).removesuffix(".__init__") for path in sources
    }
    routers = {
        modules[path]
        for path, tree in sources.items()
        if "app/api/v1/" in path.as_posix()
        and modules[path] != "app.api.v1"
        and any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "APIRouter")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "APIRouter")
            )
            for node in ast.walk(tree)
        )
    }
    violations = []
    for path, tree in sources.items():
        visitor = RuntimeDependencies(modules[path], routers)
        visitor.visit(tree)
        violations.extend(replace(v, file=path.relative_to(root).as_posix()) for v in visitor.violations)
    return violations


def check_baseline(violations: list[Violation], baseline: list[dict]) -> list[str]:
    fields = ("file", "rule", "scope", "target")
    counts: Counter[tuple[str, ...]] = Counter()
    locations: dict[tuple[str, ...], int] = {}
    for violation in violations:
        identity = violation.identity()
        key = tuple(identity[field] for field in fields)
        counts[key] += 1
        locations[key] = violation.line
    allowed = {}
    for row in baseline:
        key = tuple(row[field] for field in fields)
        if key in allowed or not row["task"] or row["count"] <= 0:
            raise ValueError(f"Invalid or duplicate migration entry: {row}")
        allowed[key] = row["count"]
    errors = []
    for key in sorted(counts.keys() | allowed.keys()):
        actual, expected = counts.get(key, 0), allowed.get(key, 0)
        if actual != expected:
            kind = "new" if actual > expected else "stale"
            location = f"{key[0]}:{locations[key]}" if key in locations else key[0]
            errors.append(
                f"{kind}: {location} [{key[1]}] {key[2] or '<module>'} -> {key[3]} ({actual}, baseline {expected})"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--inventory", action="store_true", help="Print raw findings without modifying the baseline")
    args = parser.parse_args()
    violations = scan_repository(args.root)
    if args.inventory:
        print(json.dumps([asdict(v) for v in violations], indent=2))
        return 0
    baseline = json.loads((args.root / "ci/module-boundary-baseline.json").read_text(encoding="utf-8"))
    errors = check_baseline(violations, baseline)
    for error in errors:
        print(error)
    if not errors:
        print(f"Module boundaries OK; {len(violations)} explicitly tracked migration edges")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
