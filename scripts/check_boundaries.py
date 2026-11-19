"""Which package may import which (RFC-0018, docs/wip/PHASE2-RESTRUCTURE-PLAN.md §2). Run by `make lint`.

    python3 scripts/check_boundaries.py [ROOT]

Every Python file of a project (a folder with a pyproject.toml and a src/) is read with `ast`; every import of one of the
lab's own packages is mapped to a UNIT by its module name, and the file's own unit is its module's (a file under src/) or
its project's (tests, probes, perf: they may import more, TESTS_EXTRA). An import the table does not allow is a failure,
with file, line and both units. Each project's `[tool.uv.sources]` path sources are held to the same table.

Units are named by module prefix, not by folder (MODULES), so the same table holds while the code is carved out of one
package into several, and after.

What it cannot see: a module named in a string (`python -m duck_lab.x`, `importlib`), a `PYTHONPATH` or `sys.path`
trick, an import in a file outside a project's folders. It reads imports, not behaviour.

Two lists record what the table does not allow yet: EXCEPTIONS (permanent, each with its retiring RFC) and BASELINE
(to be removed; an entry no longer needed is a failure too, so the list only shrinks)."""

import ast
import sys
import tomllib
from pathlib import Path

# module prefix -> unit; the longest matching prefix wins
MODULES = {
    "runfile": "runfile",
    "robotgate": "robotgate",
    "worldmodel": "worldmodel",
    "observatory": "observatory",
    "mission_control": "mission_control",
    "nxt_lab": "nxt_lab",
    "duck_lab": "duck_lab",
    "miniview": "observatory",
}

# who may import whom, in a project's source: libraries import no other unit, apps never import apps, robots never apps
ALLOWED = {
    "runfile": set(),
    "robotgate": set(),
    "worldmodel": set(),
    "observatory": {"runfile"},
    "mission_control": {"robotgate"},
    "nxt_lab": {"runfile"},
    "duck_lab": {"runfile", "robotgate", "worldmodel"},
}

# tests, probes and perf scripts of a project also drive neighbours: Chromium through the Observatory's shots, a run's writer
TESTS_EXTRA = {
    "observatory": set(),
    "mission_control": {"runfile", "observatory", "duck_lab", "worldmodel"},
    "nxt_lab": {"observatory"},
    "duck_lab": set(),
}

# permanent, by importing module: Mission Control's duck adapter drives the navigator over its own client (nav.client,
# nav.run.load_scale), retired by RFC-0020's plugins
EXCEPTIONS = {
    "mission_control.duck": {"duck_lab"},
}

# to be removed (each a knot cut by a later commit of the restructure)
BASELINE = {}

SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git", "site"}


def unit_of(module: str):
    parts = module.split(".")
    for n in range(len(parts), 0, -1):
        u = MODULES.get(".".join(parts[:n]))
        if u:
            return u
    return None


def projects(root: Path) -> list:
    found = set(root.glob("*/src")) | set(root.glob("*/*/src"))
    return sorted(s.parent for s in found if (s.parent / "pyproject.toml").exists()
                  and not (SKIP_DIRS & set(s.relative_to(root).parts)))


def package_names(project: Path) -> list:
    return sorted(p.name for p in (project / "src").iterdir() if p.is_dir() and (p / "__init__.py").exists())


def py_files(project: Path):
    for f in sorted(project.rglob("*.py")):
        if not SKIP_DIRS & set(f.relative_to(project).parts):
            yield f


def module_of(project: Path, f: Path):
    """The dotted module of a file under src/, else None."""
    rel = f.relative_to(project)
    if rel.parts[0] != "src":
        return None
    parts = list(rel.with_suffix("").parts[1:])
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports(tree: ast.AST, module, is_pkg: bool):
    """(line, imported module name) for every import of anything, nested ones too; a `from m import a` also gives m.a."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                if module is None:
                    continue
                pkg = module.split(".") if is_pkg else module.split(".")[:-1]
                pkg = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join(pkg + ([node.module] if node.module else []))
            full = [f"{base}.{a.name}" for a in node.names if a.name != "*"]
            if not any(n in MODULES for n in full):     # `from miniview import keys` imports the module keys, not miniview
                yield node.lineno, base
            for n in full:
                yield node.lineno, n


def check(root: Path) -> list:
    problems, used_baseline = [], set()
    provided = {}
    projs = projects(root)
    for p in projs:
        mods = {unit_of(module_of(p, f)) for f in py_files(p) if module_of(p, f)}
        provided[p.resolve()] = (mods | {unit_of(n) for n in package_names(p)}) - {None}
    for p in projs:
        pkgs = package_names(p)
        if not pkgs:
            continue
        own = unit_of(pkgs[0])
        if own is None:
            continue
        for f in py_files(p):
            rel = f.relative_to(root)
            module = module_of(p, f)
            unit = unit_of(module) if module else own
            allowed = ALLOWED[unit] | ({unit} if unit else set())
            if module is None:
                allowed |= TESTS_EXTRA.get(own, set()) | ALLOWED[own] | {own}
            try:
                tree = ast.parse(f.read_text(), str(f))
            except SyntaxError as e:
                problems.append(f"{rel}:{e.lineno}: does not parse: {e.msg}")
                continue
            seen = set()
            for line, name in imports(tree, module, f.name == "__init__.py"):
                target = unit_of(name)
                if (line, target) in seen:
                    continue
                seen.add((line, target))
                if target is None or target in allowed:
                    continue
                if module and target in EXCEPTIONS.get(module, set()):
                    continue
                if module and target in BASELINE.get(module, set()):
                    used_baseline.add(module)
                    continue
                problems.append(f"{rel}:{line}: {unit or own} imports {name} ({target}), which the table does not allow")
        try:
            src = tomllib.loads((p / "pyproject.toml").read_text()).get("tool", {}).get("uv", {}).get("sources", {})
        except tomllib.TOMLDecodeError as e:
            problems.append(f"{p.relative_to(root)}/pyproject.toml: does not parse: {e}")
            continue
        for dist, spec in src.items():
            if isinstance(spec, dict) and "path" in spec:
                dep = (p / spec["path"]).resolve()
                units = provided.get(dep)
                if units is None:
                    problems.append(f"{p.relative_to(root)}/pyproject.toml: path source {dist} = {spec['path']} is not a project here")
                elif not units & (ALLOWED[own] | TESTS_EXTRA.get(own, set()) | {own}):
                    problems.append(f"{p.relative_to(root)}/pyproject.toml: path source {dist} provides {sorted(units)}, "
                                    f"which {own} may not use")
    for module, units in BASELINE.items():
        if module not in used_baseline and any(module.split(".")[0] in package_names(p) for p in projs):
            problems.append(f"BASELINE lists {module}, which no longer breaks the table: remove the entry")
    return problems


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    problems = check(root)
    for line in problems:
        print("FAIL " + line)
    print("boundaries", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
