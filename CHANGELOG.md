# Changelog

## 0.2.0

- Default to read-only at the CLI and HTTP transport layers; require explicit write opt-in.
- Add an environment lock and a dedicated `mydata-readonly` executable.
- Add offline command discovery with per-command JSON Schemas and side-effect metadata.
- Add versioned records output with invoice projections, stable arrays and string amounts/identifiers.
- Support records/JSON page files with raw XML retained and explicit completeness manifests.
- Reject unexpected response roots, malformed statuses, document collections and continuation tokens.
- Add an agent usage guide, MIT license and synthetic regression tests.

This release changes write behavior: remote writes now require `--allow-writes` on the standard executable and cannot run under a read-only lock. Live submission workflows remain unvalidated.
