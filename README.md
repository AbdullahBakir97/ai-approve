# ai-approve

GitHub App + autonomous code-review bot. Reviews PRs via free GitHub
Models, posts structured verdicts, gates auto-merge.

## Install on your repo

See [`app/INSTALL.md`](app/INSTALL.md) for the full guide.

Quick version:
1. Create the App from the manifest URL
2. Install on your repo
3. Copy `workflows/ai-approve.yml.template` → `.github/workflows/ai-approve.yml`
4. Add 2 secrets: `AI_APPROVE_APP_ID` + `AI_APPROVE_APP_PRIVATE_KEY`
5. Seed `docs/ai-approve/` from `docs/templates/`

## What it does

- Reviews every PR via a 2-pass LLM pipeline (free GitHub Models)
- Posts structured verdicts (APPROVE / REQUEST_CHANGES / COMMENT)
- Auto-fixes mechanical issues (ruff, isort, i18n) and pushes commits
- Filters hallucinations via expected_text verification
- Specialized branches: migration deep-inspection, security review, cross-PR conflict awareness, test stub suggestions

## Permissions

- `contents: write` — auto-fix commit + push to PR branches
- `pull-requests: write` — posting reviews + labels
- `issues: write` — hidden state comment per PR
- `metadata: read` — default

See [`app/manifest.json`](app/manifest.json) for the canonical declaration.
