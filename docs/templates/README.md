# AI-Approve per-repo state

This directory holds the bot's state for ONE consumer repo.

## Files

- `lessons.md` — accumulated review rules. Prepended to the Pass 2 system prompt.
  Edited only via PR. NEVER edited inline by the bot — only via a retrospective PR.
- `calibration.json` — the bot's track record on this repo. Updated automatically each run.

The bot's source code lives at https://github.com/AbdullahBakir97/ai-approve. This
directory is local state for THIS repo's review history.

## Initial setup

Copy this entire `docs/templates/` directory to your consumer repo as `docs/ai-approve/`.
