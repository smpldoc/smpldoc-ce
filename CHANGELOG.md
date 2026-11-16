# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository scaffold: license, security policy, contribution guide, code of conduct, issue and
  pull request templates, and Dependabot for GitHub Actions.
- `scripts/check_repo.py` and its tests. It fails the build on an unpinned action or base image,
  a workflow without read-only permissions, `pull_request_target`, a download piped to a shell, or
  a committed secret.
- `_auto:deploy` and `scorecard` workflows.
- Architecture overview in `docs/ARCHITECTURE.md`.
- Core: domain models, the five ports (`MailIn`, `Blob`, `Extractor`, `Store`) and the job runner
  (ingest, extract, close) with retries, step events, crash resume, a sender trust gate and
  company scoping.
- Adapters: `relay-pull` mail (https only, bearer token, no redirects, size cap), in-memory mail,
  SQLite store, file blob, plain-text extractor.
- Shared contract tests for every port, a domain-boundary check, and a fake relay for tests.
- `docs/RELAY_PROTOCOL.md` and `docs/FEATURES.md`.
