# Contributing to FabricGate (CLI/SDK)

Thanks for your interest. This repository holds the public client side of FabricGate: the CLI, the Python SDK, the shared models and the API contracts. Bug reports, board additions, documentation fixes and features are all welcome.

## Development setup

```sh
git clone https://github.com/harurun78/fabricgate.git
cd fabricgate
uv sync                       # https://docs.astral.sh/uv/  (installs the dev group too)
uv run fabricgate --help
```

Python 3.11+ is required. `uv.lock` is committed; CI installs with `--frozen`, so run `uv lock` when you change dependencies.

## Checks that CI runs

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv build
```

All of them must pass before a pull request is merged. Tests live in `tests/unit/`; fixtures in `tests/fixtures/`.

## Changing the API contracts

`docs/contracts/` is the source of truth for the registry's public API. The wire-format JSON Schemas are generated from the models:

```sh
uv run python scripts/extract_schemas.py
```

Commit the regenerated files together with the model change and add an entry to `docs/contracts/CHANGELOG.md`. Breaking changes to the *read* API are not accepted without a migration note; the write API is still marked MVP and may change.

## Adding a board to the Board DB

Boards live in `src/fabricgate/data/board-db/official.yaml` and are validated against `docs/contracts/schemas/board-db.schema.json` (`tests/unit/test_models.py`). Add an entry with `board_id`, `device`, the supported runtimes and a source URL for the identification data, and open a pull request. No code change is needed.

## Pull requests

- One purpose per pull request; keep unrelated refactors out.
- Conventional Commits for titles (`feat(cli): ...`, `fix(sdk): ...`, `docs: ...`).
- Describe how you verified the change. Screenshots are not needed; command output is.
- Do not add secrets, tokens or personal data to tests, fixtures or CI. The workflows in this repository run without any secrets by design.
- Please reference issues from **this** repository only. The registry implementation is developed elsewhere; if a change here depends on a server-side change, describe it in words rather than linking an internal issue number.

## Reporting bugs

Open an issue with the `fabricgate --version` output, the command you ran, and the full error text (`--verbose` helps). Security problems go to the address in [SECURITY.md](SECURITY.md), not to the issue tracker.
