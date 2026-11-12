# Contributing

Thanks for your interest in contributing!

## Workflow

This project uses a single long-lived branch, **`main`**.

- Create a short-lived branch from `main` (e.g. `fix/short-description`, `feature/short-description`).
- **Open pull requests against `main`.**
- Releases are Git tags on `main`; HACS installs from GitHub releases, so `main` can move freely between releases.

## Before opening a PR

Run the same checks as CI:

```bash
ruff check .
mypy custom_components tests
pytest
python scripts/check_manifest.py
```

Keep each PR focused on one topic, and describe what it changes and why. If you change behavior, update `README.md` and the relevant file in [docs/](docs/README.md).

## Releases (maintainer)

See the release checklist in [docs/OPERATIONS.md](docs/OPERATIONS.md).
