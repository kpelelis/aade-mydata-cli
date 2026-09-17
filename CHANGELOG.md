# Changelog

## 0.3.0

- Replace the misleading invoice `direction` field with `source: received|transmitted`.
- Bump the records envelope schema to 2.0 for this breaking field rename; command-discovery and pagination-manifest schemas remain 1.0.
- Document manually reported foreign purchases and reconciliation between expense-book, received and transmitted records.
- Add a synthetic foreign-purchase regression test and expose source semantics in command discovery.

## 0.2.0

- Default to read-only at the CLI and HTTP transport layers; require explicit write opt-in.
- Add an environment lock and a dedicated `mydata-readonly` executable.
- Add offline command discovery with per-command JSON Schemas and side-effect metadata.
- Add versioned records output with invoice projections, stable arrays and string amounts/identifiers.
- Support records/JSON page files with raw XML retained and explicit completeness manifests.
- Reject unexpected response roots, malformed statuses, document collections and continuation tokens.
- Add an agent usage guide, MIT license and synthetic regression tests.

This release changes write behavior: remote writes now require `--allow-writes` on the standard executable and cannot run under a read-only lock. Live submission workflows remain unvalidated.
