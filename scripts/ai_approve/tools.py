"""Tools exposed to Pass 2 (the agentic loop): read_file, grep, list_dir.

The agent calls these via OpenAI tool-use protocol. We implement them
as plain Python functions; the dispatcher converts JSON tool_call args
into kwargs.

All paths are RESOLVED RELATIVE TO REPO ROOT. We refuse paths outside
the repo (no `..` escape) and refuse to read files larger than 256 KB.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

MAX_READ_BYTES = 256 * 1024
MAX_GREP_MATCHES = 100


# ─── Tool schemas (for the OpenAI tools= parameter) ────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repo. Optionally specify start_line and end_line (1-indexed, inclusive).",
            "parameters": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents with a regex pattern. Returns up to 100 matches as {file, line, text}.",
            "parameters": {
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List immediate contents of a directory.",
            "parameters": {
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        },
    },
]


# ─── Safety: confine paths to repo root ────────────────────────────────

def _safe_path(repo_root: Path, target: str) -> Path:
    """Resolve `target` under repo_root, refuse anything escaping it.

    Uses `Path.relative_to()` rather than string-prefix comparison,
    which would let `/repo-evil/secret` slip past a `/repo` check
    (CVE-class path-confusion bug).

    NOTE on symlinks: `resolve()` follows symlinks, so an in-tree symlink
    pointing outside the repo would pass this guard. That requires prior
    write access to the repo to plant, so the residual risk is low in
    our threat model (single-author repo + GitHub Actions checkout).
    """
    p = (repo_root / target).resolve()
    root = repo_root.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes repo root: {target!r}") from None
    return p


# ─── Tool implementations ──────────────────────────────────────────────

def read_file(repo_root: Path, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    p = _safe_path(repo_root, path)
    if not p.exists():
        return f"<file not found: {path}>"
    if not p.is_file():
        return f"<not a file: {path}>"
    size = p.stat().st_size
    if size > MAX_READ_BYTES:
        return f"<file too large ({size} bytes); aborted>"
    text = p.read_text(encoding="utf-8", errors="replace")
    if start_line is None and end_line is None:
        return text
    lines = text.splitlines()
    s = max(1, start_line or 1) - 1
    e = min(len(lines), end_line or len(lines))
    return "\n".join(lines[s:e])


def grep(repo_root: Path, pattern: str, path: str | None = None, glob: str | None = None) -> list[dict]:
    # Use `git grep` for speed + .gitignore awareness.
    # Build the command WITHOUT a `--` separator first; if any pathspec
    # follows, add `--` exactly once before the pathspec(s). A double
    # `--` would silence the pattern by treating it as a pathspec.
    cmd = ["git", "-C", str(repo_root), "grep", "-n", "-E", pattern]
    if glob:
        cmd += ["--", f":(glob){glob}"]
    elif path:
        cmd += ["--", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    matches: list[dict] = []
    for line in (out.stdout or "").splitlines():
        # Format: "<file>:<lineno>:<text>"
        m = re.match(r"^([^:]+):(\d+):(.*)$", line)
        if m:
            matches.append({"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)})
        if len(matches) >= MAX_GREP_MATCHES:
            break
    return matches


def list_dir(repo_root: Path, path: str) -> list[dict]:
    p = _safe_path(repo_root, path)
    if not p.exists() or not p.is_dir():
        return []
    return [
        {"name": child.name, "kind": "dir" if child.is_dir() else "file"}
        for child in sorted(p.iterdir())
    ]


# ─── Dispatcher (called by deep_review's agentic loop) ─────────────────

def dispatch(name: str, args: dict, repo_root: Path) -> str:
    """Call the named tool; return its result as a string (for the LLM)."""
    if name == "read_file":
        return read_file(repo_root, **args)
    if name == "grep":
        result = grep(repo_root, **args)
        return "\n".join(f"{m['file']}:{m['line']}: {m['text']}" for m in result) or "(no matches)"
    if name == "list_dir":
        result = list_dir(repo_root, **args)
        return "\n".join(f"{e['name']}/" if e["kind"] == "dir" else e["name"] for e in result) or "(empty)"
    return f"<unknown tool: {name}>"
