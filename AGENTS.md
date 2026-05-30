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
- Before commiting use @claude-reviewer agent to check

## Database
- Use migrations for schema changes under `supabase/migrations/`.
- Do not hardcode generated IDs in migrations unless there is a clear, stable business requirement.
- Be careful with destructive DDL or data changes; call out risks before applying them.

## Verification
- For Python changes, run at least `uv run ruff check .` when feasible.
- Run `uv run black .` after editing Python files unless the change is trivial and already formatted.
- For extension changes, manually inspect `extension/manifest.json`, `extension/popup.html`, and related JS for consistency.
- for running the scrapping run `uv run python -m app.main --force-full` use --force-full for full load and without it for delta 

## Collaboration
- Do not revert user changes unless explicitly asked.
- If the working tree has unrelated modifications, leave them alone.
- Before large edits, inspect the relevant files and make the smallest correct change.
- ALWAYS inspect and make the smallest changes to achive the desired goal
