"""
tests/test_legacy_cutover.py -- the regression gate that keeps the retired
Node.js dashboard and the four legacy Python loggers gone (GND-03, CAP-01).

These files were kept through the entirety of Phase 1 for rollback safety:
CAP-01's "duplicate implementation removed from the repository" clause was
deliberately deferred at the Phase 1 -> 2 boundary (`01-CONTEXT.md`
`<deferred>`), and the requirement it blocks has already been marked
Complete once in error and reverted (`01-13-SUMMARY.md`). A deletion is not
a checkable state on its own -- "we deleted it" is a claim until something
keeps failing if it ever comes back. This file is that something: it fails
if any of the six retired paths reappears, if anything under `src/` or
`tests/` ever imports one of the four removed logger modules again, or if
the project's own instruction file goes back to documenting a system that
no longer exists (this project's #1 recorded anti-pattern -- prose
outliving what produced it).

Written and run BEFORE 02-04's deletion task, deliberately -- a cutover
test authored after the files are already gone has never once been
observed to fail, and cannot be trusted to be looking at the right paths.
"""

import ast
from pathlib import Path

# Repository root, resolved relative to this file (never a hardcoded
# absolute path) -- same convention `src/telemetry/logger/config.py` uses
# for `_REPO_ROOT`, and the same one `tests/test_end_to_end.py` already
# uses for `REPO_ROOT`.
REPO_ROOT = Path(__file__).resolve().parent.parent

# The whole directory that held the Node server, its simulator, its
# README, and the original dashboard (GND-03, D-13).
NODE_DASHBOARD_DIR = REPO_ROOT / "can-dashboard"

# The four superseded car-side modules CAP-01's second clause names
# (D-14): the two legacy loggers, the shared reference helper, and the CAN
# sender. Bare module names (no `.py`), matching Python import-statement
# syntax rather than filenames.
LEGACY_LOGGER_MODULE_NAMES = (
    "neoVI_logger",
    "new_logger",
    "references",
    "neoVI_sender",
)

LEGACY_LOGGER_FILES = tuple(
    REPO_ROOT / "src" / f"{name}.py" for name in LEGACY_LOGGER_MODULE_NAMES
)

CLAUDE_MD = REPO_ROOT / ".claude" / "CLAUDE.md"

# Phrases naming the retired Node dashboard system specifically. Deliberately
# NOT bare "stdin"/"stdout" -- this codebase's *current* stderr-for-humans/
# stdout-for-machine-records convention is legitimate documentation and must
# survive. What must NOT survive is prose describing the two-process
# stdin/stdout pipe *between the Python logger and the Node server*, which
# disappears entirely once every Node.js/npm/WebSocket/can-dashboard mention
# is gone.
REMOVED_SYSTEM_PHRASES = (
    "can-dashboard",
    "server.js",
    "simulate.js",
    "Node.js",
    "WebSocket",
    "npm",
)


def _iter_python_files():
    """Every `.py` file under the source and test roots, this file
    excluded (it necessarily names the removed modules itself, in data,
    not in an import statement)."""
    self_path = Path(__file__).resolve()
    for root in (REPO_ROOT / "src", REPO_ROOT / "tests"):
        for path in root.rglob("*.py"):
            if path.resolve() == self_path:
                continue
            yield path


def _imported_module_roots(path: Path):
    """Parse `path` with `ast` and yield the root module name of every
    `import X` / `import X.Y` / `from X import Y` / `from X.Y import Z`
    statement in it.

    `ast`-based, not regex, so this is syntax-precise the way the blast-
    radius audit's manual read was: a docstring or comment that merely
    *names* a removed module ("this deliberately departs from what
    `new_logger.py` did") is prose, not an import statement, and must never
    be flagged -- matching on the bare name would make this test fail on
    prose forever, exactly what the audit's own methodology avoided.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module.split(".")[0]


def test_node_dashboard_directory_removed():
    """Catches a partial deletion that leaves the retired server sitting
    next to its replacement, where someone will eventually run it."""
    assert not NODE_DASHBOARD_DIR.exists(), (
        f"{NODE_DASHBOARD_DIR} still exists -- the Node server, its "
        "simulator, its README, and the original dashboard must be "
        "removed entirely (GND-03), not partially deleted."
    )


def test_legacy_logger_modules_removed():
    """Catches the same partial-deletion failure mode for the car side --
    the literal text of CAP-01's outstanding clause."""
    still_present = [str(p) for p in LEGACY_LOGGER_FILES if p.exists()]
    assert not still_present, (
        f"legacy logger module(s) still present, but CAP-01 requires the "
        f"duplicate implementation removed from the repository: {still_present}"
    )


def test_nothing_imports_the_removed_modules():
    """Scans every Python file under `src/` and `tests/` for a real import
    statement naming one of the four removed modules. Encodes the same
    distinction the deletion blast-radius audit used (import syntax, never
    a bare-name match) to conclude the deletion was safe."""
    offenders = []
    for path in _iter_python_files():
        for root in _imported_module_roots(path):
            if root in LEGACY_LOGGER_MODULE_NAMES:
                offenders.append(f"{path}: imports {root!r}")
    assert not offenders, (
        f"file(s) still import a removed legacy module: {offenders}"
    )


def test_instruction_file_does_not_document_removed_code():
    """Catches this project's #1 recorded failure mode: documentation
    describing a system that no longer exists. This is what makes '.claude/
    CLAUDE.md describes only code that exists' a checkable state rather
    than a matter of opinion."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    hits = [phrase for phrase in REMOVED_SYSTEM_PHRASES if phrase in text]
    hits += [f"{name}.py" for name in LEGACY_LOGGER_MODULE_NAMES if f"{name}.py" in text]
    assert not hits, f"{CLAUDE_MD} still references removed code: {hits}"
