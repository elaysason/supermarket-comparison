# Agent Instructions

## Project Overview
- This repo is a Python supermarket comparison project with a FastAPI app, scraper code, database repository code, Supabase migrations, and a browser extension.
- The goal is to allow user to get the best price when ordering groceries online
- Main Python package code lives under `app/`.
- Browser extension files live under `extension/`.
- Database migrations live under `supabase/migrations/`.

## Environment
- Python version: `>=3.10`.
- Dependency manager: `uv`.
- Do not commit `.env`, `.venv/`, downloaded XML files, cache directories, or editor-local config.
- Treat supermarket XML/download data as local artifacts unless explicitly asked otherwise.

## Common Commands
- Install dependencies: `uv sync`
- Run API locally: `uv run uvicorn app.api.main:app --reload`
- Format Python: `uv run black .`
- Lint Python: `uv run ruff check .`

## Code Style
- Keep Python formatted with Black, line length 88.
- Keep Ruff issues clean for enabled rules: `E`, `F`, and `W`.
- Prefer small, direct changes over broad rewrites.
- Preserve existing module boundaries unless a refactor is explicitly requested.
- Keep scraper logic chain-specific under `app/scrapers/chains/` and shared behavior in `app/scrapers/common.py` or `app/scrapers/base.py`.
- Before committing, invoke the reviewer from the opposite model family (Claude session -> `gpt-reviewer`, GPT session -> `claude-reviewer`, otherwise default to `gpt-reviewer`).

## Database
- Use migrations for schema changes under `supabase/migrations/`.
- Do not hardcode generated IDs in migrations unless there is a clear, stable business requirement.
- Be careful with destructive DDL or data changes; call out risks before applying them.

## Verification
- For Python changes, run `uv run ruff check .` and relevant tests (`uv run pytest`) when feasible.
- Format only changed Python files with Black unless the change is trivial and already formatted.
- For extension changes, manually inspect `extension/manifest.json`, `extension/popup.html`, and related JS for consistency.
- To run the scraper use `uv run python -m app.main`; add `--force-full` for a full load and omit it for a delta. This writes data, so confirm the target environment before running.

## Collaboration
- Do not revert user changes unless explicitly asked.
- If the working tree has unrelated modifications, leave them alone.
- Before large edits, inspect the relevant files and make the smallest correct change.
