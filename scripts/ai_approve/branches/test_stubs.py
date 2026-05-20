"""Test stub suggestions branch — drafts pytest stubs for new public functions.

LLM call: gpt-4.1-mini. Output is informational only — suggestions land as
`severity: info` comments with `suggested_text` blocks. Aggregator never
blocks merge on these.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

from ..models_client import chat_completion

HERE = Path(__file__).parent.parent
PROMPT_PATH = HERE / "prompts" / "branch_test_stubs_system.md"
SCHEMA_PATH = HERE / "schemas" / "branch_test_stubs.json"

MODEL = "openai/gpt-4.1-mini"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def find_new_public_functions(diff: str) -> list[dict]:
    """Parse unified diff; return [{file, line, name}] for newly added
    PUBLIC top-level Python functions only.

    Filters: skips names starting with `_`, skips indented (method) defs.
    """
    funcs: list[dict] = []
    current_file: str | None = None
    current_new_line = 0

    for line in diff.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+?)$", line)
        if m:
            current_file = m.group(2)
            continue
        m = re.match(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@", line)
        if m:
            current_new_line = int(m.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            m = re.match(r"^def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(", content)
            if m and current_file and current_file.endswith(".py"):
                funcs.append({
                    "file": current_file,
                    "line": current_new_line,
                    "name": m.group(1),
                })
            current_new_line += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue
        current_new_line += 1

    return funcs[:5]  # cap at 5 stubs per PR


def run_test_stubs_branch(*, diff: str, token: str) -> dict:
    """Run the test-stubs branch.

    Returns {"comments": [...]} with severity=info per stub.
    """
    funcs = find_new_public_functions(diff)
    if not funcs:
        return {"comments": []}

    system = PROMPT_PATH.read_text(encoding="utf-8")
    schema = _load_schema()
    user = "Newly added public functions:\n\n" + "\n".join(
        f"- {f['file']}:{f['line']}  def {f['name']}()" for f in funcs
    )

    try:
        result = chat_completion(
            model=MODEL, token=token,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=None,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "test_stubs_v1", "schema": schema, "strict": True},
            },
            temperature=0.0,
        )
        if not result.content or not result.content.strip():
            return {"comments": []}
        parsed = json.loads(result.content)
        jsonschema_validate(instance=parsed, schema=schema)
    except (Exception, json.JSONDecodeError, ValidationError):
        return {"comments": []}

    comments: list[dict] = []
    for stub in parsed.get("stubs", []):
        comments.append({
            "file": stub["for_file"],
            "line": stub["for_line"],
            "expected_text": "",
            "claim": f"Suggested test stub for `{stub['for_function']}`",
            "severity": "info",
            "suggested_text": stub["stub_code"],
        })
    return {"comments": comments}
