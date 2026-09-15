# FabricGate

[![PyPI](https://img.shields.io/pypi/v/fabricgate.svg)](https://pypi.org/project/fabricgate/)
[![Python](https://img.shields.io/pypi/pyversions/fabricgate.svg)](https://pypi.org/project/fabricgate/)
[![CI](https://github.com/harurun78/fabricgate/actions/workflows/ci.yaml/badge.svg)](https://github.com/harurun78/fabricgate/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Discover, pull and verify FPGA designs for your board — one command, any runtime.**

FabricGate is a package registry for FPGA designs (bitstreams plus the metadata a runtime needs to load them). This repository contains the client side: the `fabricgate` CLI, the Python SDK, the shared data models, and the public API contracts. The hosted registry lives at `https://registry.fabricgate.dev`.

> **Status: alpha (0.1.0).** The registry is being seeded with community PYNQ overlays. Interfaces marked *stable* in `docs/specs/` are kept backward compatible; everything else may still change before 1.0.

## Install

```sh
pip install fabricgate
```

Python 3.11 or newer. `fgate` is installed as a short alias of `fabricgate`.

## Three steps to a running design

```sh
# 1. Find a design for your board
fabricgate search --platform pynq-z2/pynq adder

# 2. Pull it (bitstream + hwh + manifest, digests verified on download)
fabricgate pull example/adder-demo:1.0.0 --platform pynq-z2/pynq

# 3. Load it with the runtime you already use
python -c "from pynq import Overlay; ol = Overlay('adder-demo/adder.bit')"
```

`example/adder-demo` is a placeholder name; run `fabricgate search` to see what is actually published. The `--platform` value is `<board>/<runtime>`; run `fabricgate pull --help` for the resolution rules, including the `generic-<device>` fallback.

## What the CLI can do

| Command | Purpose |
|---|---|
| `search`, `info`, `diff`, `stats`, `watch` | discover designs and track updates |
| `pull`, `verify`, `list` | download with digest verification, re-verify, inspect the local cache |
| `build`, `push`, `yank`, `deprecate` | publish your own designs (`build` generates the Platform Manifest and Design Index from a build directory) |
| `login`, `token`, `quota`, `webhook`, `license-check` | account, automation and policy helpers |

`fabricgate --json` gives machine-readable output for every command.

## Supported boards and runtimes

The bundled Board DB (`src/fabricgate/data/board-db/official.yaml`) currently knows these boards:

| Board | Device | Runtime |
|---|---|---|
| `pynq-z2` | xc7z020 | `pynq` |
| `zcu104` | xczu7ev | `pynq`, `linux-fpgamgr` |
| `pico-ice` | iCE40UP5K | `nanopynq` (Phase 3, forward reference) |
| `generic-xc7z020`, `generic-xczu7ev` | — | device-level fallback for boards not yet listed |

Adding a board is a data change; see [CONTRIBUTING.md](CONTRIBUTING.md).

## SDK

```python
from fabricgate.sdk import api

result = api.pull("example/adder-demo:1.0.0", platform="pynq-z2/pynq")
print(result.artifacts)
```

The SDK wraps the same client the CLI uses. See `docs/specs/client-behavior.md` for the resolution and caching rules.

## Public contracts

`docs/contracts/` is the source of truth for the registry's public API:

- `openapi.yaml` / `openapi.json` — Registry HTTP API
- `schemas/design-index.schema.json`, `schemas/platform-manifest.schema.json`, `schemas/board-db.schema.json` — wire formats
- `CHANGELOG.md` — contract changes and migration notes

Specifications for the CLI, client behaviour and data formats are in `docs/specs/`.

## Self-hosting and the registry implementation

The registry server is operated as a hosted service and its implementation is not published at this stage (see `docs/specs/` for the distribution policy summary in `client-behavior.md`). Everything a client needs to interoperate — API, schemas, error formats — is in this repository, so alternative implementations are possible.

## Contributing, security, license

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, tests, pull requests
- [SECURITY.md](SECURITY.md) — how to report a vulnerability
- [LICENSE](LICENSE) — MIT

## Verifying what you install

Every release is published from this repository via PyPI Trusted Publishing and carries a GitHub build-provenance attestation:

```sh
pip download --no-deps fabricgate==0.1.0
gh attestation verify fabricgate-0.1.0-py3-none-any.whl --repo harurun78/fabricgate
```
