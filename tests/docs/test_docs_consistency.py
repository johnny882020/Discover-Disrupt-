"""Deterministic evals that fail when the documentation and the code disagree.

The docs in ``docs/``, ``README.md``, ``CLAUDE.md`` and ``PRIVACY_POLICY.md``
are written by hand. They restate contracts that live in code: the API's
routes, the database tables and migrations, the exception hierarchy, enum
vocabularies and settings. Nothing ties the two together, so every change to
the code can silently leave a doc stale. These tests read the facts from the
code (the OpenAPI spec, the ORM metadata, the Alembic scripts, the enums) and
compare them with what the Markdown says, in both directions where the doc
claims to be complete.

A failure here is a finding about the docs (or the code), never something to
fix by loosening a check. If a check fails because the Markdown is written in
a shape the parser does not understand, fix the parser.
"""

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from dndlabs.api.app import create_app
from dndlabs.core import exceptions
from dndlabs.core.config import Settings
from dndlabs.core.schemas import ColumnRole, RunProgress, RunStage, RunStatus, UploadFormat
from dndlabs.storage.database import MIGRATIONS_DIR, head_revision
from dndlabs.storage.models import Base
from dndlabs.validation import assay_context

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
API_MD = DOCS_DIR / "api.md"
ARCHITECTURE_MD = DOCS_DIR / "architecture.md"
DEPLOYMENT_MD = DOCS_DIR / "deployment.md"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"
API_PREFIX = "/api/v1"
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

LINKED_DOCS: tuple[Path, ...] = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "PRIVACY_POLICY.md",
    *sorted(DOCS_DIR.glob("*.md")),
)

# --------------------------------------------------------------------------
# Markdown helpers
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BACKTICK = re.compile(r"`([^`]+)`")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_PATH_PARAM = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True)
class Table:
    """A Markdown table: its header cells and body rows (raw cell text)."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def column(self, name: str) -> int:
        """Return the index of the header cell whose text (sans backticks) is ``name``."""
        cleaned = [strip_code(cell).lower() for cell in self.header]
        return cleaned.index(name.lower())


def read(path: Path) -> str:
    """Return a file's text."""
    return path.read_text(encoding="utf-8")


def strip_code(cell: str) -> str:
    """Remove backticks and surrounding whitespace from a cell."""
    return cell.replace("`", "").strip()


def code_spans(text: str) -> list[str]:
    """Return the contents of every inline code span in ``text``.

    Fenced code blocks are skipped (their backticks would pair with inline
    ones), and a span never crosses a blank line.
    """
    prose = "\n".join(line for line, outside in outside_fences(text.splitlines()) if outside)
    spans: list[str] = []
    for paragraph in re.split(r"\n\s*\n", prose):
        spans.extend(span.strip() for span in _BACKTICK.findall(paragraph))
    return spans


def outside_fences(lines: Iterable[str]) -> list[tuple[str, bool]]:
    """Tag each line with whether it lies outside a fenced code block."""
    tagged: list[tuple[str, bool]] = []
    fenced = False
    for line in lines:
        if _FENCE.match(line):
            tagged.append((line, False))
            fenced = not fenced
            continue
        tagged.append((line, not fenced))
    return tagged


def section(text: str, heading: str) -> str:
    """Return the body under the first heading named ``heading``.

    The section runs until the next heading of the same or a higher level.
    Headings inside fenced code blocks are ignored. Matching ignores case and
    backticks.

    Raises:
        AssertionError: If no such heading exists.
    """
    wanted = heading.strip().lower()
    body: list[str] = []
    level: int | None = None
    for line, prose in outside_fences(text.splitlines()):
        match = _HEADING.match(line) if prose else None
        if level is None:
            if match and strip_code(match.group(2)).lower() == wanted:
                level = len(match.group(1))
            continue
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    assert level is not None, f"heading {heading!r} not found"
    return "\n".join(body)


def split_row(line: str) -> tuple[str, ...]:
    """Split a table row on unescaped pipes, dropping the outer empty cells."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return tuple(cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(stripped))


def tables(text: str) -> list[Table]:
    """Return every Markdown table in ``text`` (outside code fences)."""
    lines = [line for line, prose in outside_fences(text.splitlines()) if prose]
    found: list[Table] = []
    index = 0
    while index < len(lines) - 1:
        line = lines[index].strip()
        if line.startswith("|") and _TABLE_DIVIDER.match(lines[index + 1]):
            header = split_row(line)
            rows: list[tuple[str, ...]] = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(split_row(lines[index]))
                index += 1
            found.append(Table(header, tuple(rows)))
            continue
        index += 1
    return found


def table_with(text: str, *headers: str) -> Table:
    """Return the first table whose header contains every one of ``headers``."""
    wanted = {name.lower() for name in headers}
    for table in tables(text):
        if wanted <= {strip_code(cell).lower() for cell in table.header}:
            return table
    raise AssertionError(f"no table with columns {sorted(wanted)}")


def github_slug(heading: str) -> str:
    """Return GitHub's anchor for a heading (before de-duplication)."""
    text = re.sub(r"`|\*\*|__", "", heading).strip().lower()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # a link keeps its label
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """Return every heading anchor GitHub generates for a Markdown file."""
    seen: dict[str, int] = {}
    result: set[str] = set()
    for line, prose in outside_fences(read(path).splitlines()):
        match = _HEADING.match(line) if prose else None
        if not match:
            continue
        slug = github_slug(match.group(2))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def difference_message(what: str, missing: set[str], extra: set[str], where: str) -> str:
    """Describe a two-way set mismatch between the code and a doc."""
    parts = [f"{what} disagree with {where}:"]
    if missing:
        parts.append(f"  in the code but not the doc: {sorted(missing)}")
    if extra:
        parts.append(f"  in the doc but not the code: {sorted(extra)}")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# 1. API routes
# --------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    """Drop a query string and replace every path parameter with ``{}``."""
    return _PATH_PARAM.sub("{}", path.split("?", 1)[0].strip())


def code_operations() -> set[str]:
    """Return ``"METHOD /path"`` for every operation in the app's OpenAPI spec."""
    spec = create_app().openapi()
    return {
        f"{method.upper()} {normalize_path(path)}"
        for path, item in spec["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }


def doc_operations() -> set[str]:
    """Return ``"METHOD /path"`` for every route row in docs/api.md.

    Section tables list paths relative to ``/api/v1``; the health table
    lists absolute ones (``/``, ``/health``, ``/api/v1/...``). A cell may
    hold several comma-separated paths.
    """
    operations: set[str] = set()
    for table in tables(read(API_MD)):
        try:
            method_col, path_col = table.column("method"), table.column("path")
        except ValueError:
            continue
        for row in table.rows:
            method = strip_code(row[method_col]).upper()
            for path in code_spans(row[path_col]) or [strip_code(row[path_col])]:
                absolute = path in {"/", "/health"} or path.startswith(API_PREFIX)
                full = path if absolute else f"{API_PREFIX}{path}"
                operations.add(f"{method} {normalize_path(full)}")
    return operations


def test_api_routes_match_docs() -> None:
    code, docs = code_operations(), doc_operations()
    assert code == docs, difference_message("API routes", code - docs, docs - code, "docs/api.md")


# --------------------------------------------------------------------------
# 2-3. Database schema and migrations
# --------------------------------------------------------------------------


def test_orm_tables_match_database_schema_table() -> None:
    body = section(read(ARCHITECTURE_MD), "Database schema")
    documented = {strip_code(row[0]) for row in table_with(body, "Table").rows}
    code = set(Base.metadata.tables)
    assert code == documented, difference_message(
        "ORM tables", code - documented, documented - code, "architecture.md 'Database schema'"
    )


def test_alembic_head_matches_docs() -> None:
    match = re.search(r"Alembic head:\s*`([^`]+)`", read(ARCHITECTURE_MD))
    assert match, "architecture.md has no 'Alembic head: `NNNN`.' line"
    assert match.group(1) == head_revision(), (
        f"architecture.md says Alembic head `{match.group(1)}`, "
        f"the code's head is `{head_revision()}`"
    )


def test_revision_table_has_one_row_per_migration() -> None:
    body = section(read(ARCHITECTURE_MD), "Database schema")
    documented = [strip_code(row[0]) for row in table_with(body, "Revision").rows]
    files = sorted(p.name for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_"))
    revisions = {rev.revision for rev in ScriptDirectory(str(MIGRATIONS_DIR)).walk_revisions()}
    duplicates = sorted({rev for rev in documented if documented.count(rev) > 1})
    assert not duplicates, f"architecture.md revision table repeats {duplicates}"
    assert len(documented) == len(files), (
        f"architecture.md revision table has {len(documented)} rows, "
        f"there are {len(files)} migration files: {files}"
    )
    assert set(documented) == revisions, difference_message(
        "Alembic revisions",
        revisions - set(documented),
        set(documented) - revisions,
        "architecture.md revision table",
    )


# --------------------------------------------------------------------------
# 4. Exception hierarchy
# --------------------------------------------------------------------------

_TREE_NAME = re.compile(r"[A-Za-z_]\w*")


def doc_exception_tree() -> dict[str, str | None]:
    """Parse the exceptions tree in architecture.md into ``{name: parent}``.

    Each level indents the name by four columns (``├── ``, ``│   ``);
    trailing ``# comments`` are ignored.
    """
    body = section(read(ARCHITECTURE_MD), "Exceptions (core/exceptions.py)")
    block = re.search(r"```[^\n]*\n(.*?)```", body, re.DOTALL)
    assert block, "architecture.md 'Exceptions' section has no code block"
    parents: dict[str, str | None] = {}
    stack: list[str] = []
    for line in block.group(1).splitlines():
        text = line.split("#", 1)[0].rstrip()
        match = _TREE_NAME.search(text)
        if not match:
            continue
        depth = match.start() // 4
        del stack[depth:]
        parents[match.group(0)] = stack[-1] if stack else None
        stack.append(match.group(0))
    return parents


def code_exception_tree() -> dict[str, str | None]:
    """Return ``{name: parent}`` for DndLabsError and all its subclasses."""
    parents: dict[str, str | None] = {exceptions.DndLabsError.__name__: None}
    pending: list[type[BaseException]] = [exceptions.DndLabsError]
    while pending:
        cls = pending.pop()
        for sub in cls.__subclasses__():
            parents[sub.__name__] = cls.__name__
            pending.append(sub)
    return parents


def test_exception_tree_matches_docs() -> None:
    code, docs = code_exception_tree(), doc_exception_tree()
    wrong_parent = {
        f"{name}: doc says under {docs[name]}, code under {parent}"
        for name, parent in code.items()
        if name in docs and docs[name] != parent
    }
    message = difference_message(
        "Exception classes", set(code) - set(docs), set(docs) - set(code), "architecture.md tree"
    )
    assert set(code) == set(docs), message
    assert not wrong_parent, f"exception parents disagree: {sorted(wrong_parent)}"


# --------------------------------------------------------------------------
# 5-7. Vocabularies
# --------------------------------------------------------------------------


def column_mapping_paragraph() -> str:
    """Return the api.md paragraph that lists every ``column_mapping`` role."""
    for paragraph in re.split(r"\n\s*\n", read(API_MD)):
        if "`column_mapping`" in paragraph and "role" in paragraph:
            return paragraph
    raise AssertionError("api.md has no paragraph listing the column_mapping roles")


def test_column_roles_listed_in_api_docs() -> None:
    documented = set(code_spans(column_mapping_paragraph())) - {"column_mapping"}
    code = {role.value for role in ColumnRole}
    assert code == documented, difference_message(
        "ColumnRole values", code - documented, documented - code, "api.md column_mapping roles"
    )


def assay_row(role: str) -> set[str]:
    """Return the normalized accepted values api.md lists for an assay role."""
    for table in tables(read(API_MD)):
        header = [strip_code(cell).lower() for cell in table.header]
        column = next((i for i, cell in enumerate(header) if cell.startswith("accepted")), None)
        if header[0] != "role" or column is None:
            continue
        for row in table.rows:
            if strip_code(row[0]) == role:
                return {assay_context._normalize(value) for value in code_spans(row[column])}
        raise AssertionError(f"api.md assay-roles table has no `{role}` row")
    raise AssertionError("api.md has no table with a 'Role' and an 'Accepted values…' column")


@pytest.mark.parametrize(
    ("role", "accepted"),
    [
        ("assay_format", set(assay_context._FORMATS)),
        ("control", set(assay_context._CONTROLS)),
    ],
)
def test_assay_values_match_api_docs(role: str, accepted: set[str]) -> None:
    documented = assay_row(role)
    assert accepted == documented, difference_message(
        f"Accepted `{role}` values", accepted - documented, documented - accepted, "api.md"
    )


def test_upload_formats_in_contracts_table() -> None:
    body = section(read(ARCHITECTURE_MD), "Contracts (core/schemas.py)")
    rows = [row for row in table_with(body, "Model").rows if "`UploadFormat`" in row[0]]
    assert rows, "architecture.md contracts table has no `UploadFormat` row"
    documented = set(code_spans(" ".join(rows[0][1:])))
    missing = {fmt.value for fmt in UploadFormat} - documented
    assert not missing, f"UploadFormat values missing from the contracts table: {sorted(missing)}"


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("RunStatus", [status.value for status in RunStatus]),
        ("RunStage", [stage.value for stage in RunStage]),
        ("RunProgress", list(RunProgress.model_fields)),
    ],
)
def test_run_vocabulary_in_pipelines_section(name: str, values: list[str]) -> None:
    documented = set(code_spans(section(read(API_MD), "Pipelines")))
    missing = sorted(set(values) - documented)
    assert not missing, f"{name} values missing from api.md 'Pipelines': {missing}"


# --------------------------------------------------------------------------
# 8. Worker settings
# --------------------------------------------------------------------------

WORKER_VARS = sorted(
    f"DNDLABS_{name.upper()}" for name in Settings.model_fields if name.startswith("worker_")
)


def test_worker_settings_in_deployment_configuration() -> None:
    body = section(read(DEPLOYMENT_MD), "Configuration")
    documented = {span for row in table_with(body, "Variable").rows for span in code_spans(row[0])}
    missing = sorted(set(WORKER_VARS) - documented)
    assert not missing, f"worker settings missing from deployment.md 'Configuration': {missing}"


def test_worker_settings_in_architecture() -> None:
    documented = set(code_spans(read(ARCHITECTURE_MD)))
    missing = sorted(set(WORKER_VARS) - documented)
    assert not missing, f"worker settings missing from architecture.md: {missing}"


# --------------------------------------------------------------------------
# 9. Relative links
# --------------------------------------------------------------------------

_LINK = re.compile(r"(?<!!)\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_EXTERNAL = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def relative_links(path: Path) -> list[str]:
    """Return every relative link target in a Markdown file, outside code."""
    prose = "\n".join(line for line, outside in outside_fences(read(path).splitlines()) if outside)
    prose = re.sub(r"`[^`\n]*`", "", prose)
    return [target for target in _LINK.findall(prose) if not _EXTERNAL.match(target)]


def broken_link(source: Path, target: str) -> str | None:
    """Describe why a relative link is broken, or return None when it resolves."""
    file_part, _, anchor = target.partition("#")
    resolved = (source.parent / file_part).resolve() if file_part else source
    if not resolved.exists():
        return f"{target}: {os.path.relpath(resolved, REPO_ROOT)} does not exist"
    if anchor and resolved.suffix == ".md" and anchor not in anchors(resolved):
        return f"{target}: no heading with anchor #{anchor} in {resolved.name}"
    return None


@pytest.mark.parametrize("doc", LINKED_DOCS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    broken = [problem for target in relative_links(doc) if (problem := broken_link(doc, target))]
    assert not broken, f"broken links in {doc.relative_to(REPO_ROOT)}:\n  " + "\n  ".join(broken)
