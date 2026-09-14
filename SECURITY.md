# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | yes       |
| < 0.1   | no        |

## Reporting a vulnerability

Please report vulnerabilities privately. **Do not open a public GitHub issue.**

1. Email **security@fabricgate.dev** with the subject `[SECURITY] <brief description>`.
2. Include a description, steps to reproduce, the potential impact, and a suggested fix if you have one.

| Step | Timeline |
|------|----------|
| Acknowledgement | within 48 hours |
| Initial assessment | within 5 business days |
| Fix and disclosure | within 90 days (coordinated disclosure) |

Reporters are credited in the release notes unless they ask to stay anonymous.

## Scope

In scope for this repository:

- the `fabricgate` CLI (`src/fabricgate/cli/`)
- the Python SDK and client (`src/fabricgate/sdk/`, `src/fabricgate/client/`)
- the shared models and the published contracts (`src/fabricgate/models/`, `docs/contracts/`)
- the release pipeline (`.github/workflows/release.yaml`): PyPI Trusted Publishing with build provenance

Issues in the hosted registry service (`registry.fabricgate.dev`) are also welcome at the same address; they are handled by the same team.

Out of scope: third-party dependencies (report upstream), social engineering, and denial of service against the hosted service.

## Verifying what you install

Releases are published to PyPI from this repository via Trusted Publishing, and every wheel and sdist carries a GitHub build-provenance attestation. You can check a downloaded file with:

```sh
gh attestation verify fabricgate-<version>-py3-none-any.whl --repo harurun78/fabricgate
```
