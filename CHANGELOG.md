# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Base image moved from Debian 12 (bookworm) to Debian 13 (trixie), same Python 3.12, pinned by
  digest. The bookworm image carried a fixable high-severity PAM finding that its upstream image had
  not yet picked up, which failed the image scan. The build now also applies Debian's security fixes
  to the packages already in the image (no new packages), so a lagging upstream image cannot fail the
  scan gate or ship a fixable finding.

### Added

- Bundles are written (roadmap step 2). Each readable document (plain text today) becomes a v1.0 bundle in
  `<data dir>/bundles/<company>/<bundle id>/`, written whole or not at all, with a `bundle` step event. A new
  `BundleStore` port with a folder adapter and an in-memory adapter that pass one shared contract test, a
  pure writer (`domain/bundle_writer.py`), and `Store.get_company`. Every bundle it writes passes the
  validator, including through the real service in `tests/test_main.py`. PDFs and images are skipped with a
  recorded reason until they can be read.
- Image job in CI: the container is stopped hard and started again on the same volume, and the data it
  wrote (a company) must still be there. It also writes a CycloneDX software bill of materials and keeps
  it with the run for 30 days. `tests/test_release_gates.py` keeps these steps from being removed.
- `docs/ROADMAP.md` (Chapter 2: the document bundle) and the draft bundle contract
  `docs/BUNDLE_FORMAT.md`. Planning only, no behaviour change.
- Bundle format v1.0: a JSON Schema per bundle file, a fictional example bundle, and a validator that
  checks hashes, sizes, safe paths, unlisted files, word references and the card size, reads newer
  minor versions leniently and refuses a newer major. A small standard-library JSON Schema checker
  that refuses any keyword it does not implement. `bundle-validate FOLDER` (refuses links).
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
- Entry point `python -m smpldoc` (`run`, `check-config`, `add-company`), environment-only config
  with secret files and unknown-setting errors, and a closed health server.
- Exposure safety: refuses a public bind when a protected route has no sign-in, probes protected
  routes anonymously at start, protected routes fail closed.
- `s3-inbox` mail source for Amazon SES: reads a private bucket, hands each message out once, moves
  collected mail to `processed/` and anything oversize or unroutable to `quarantine/`, and trusts only the
  topmost `Authentication-Results` header that names `amazonses.com`.
- AWS SigV4 signing on the standard library (checked against AWS's documented examples and botocore) and
  credential providers for env keys, ECS task roles and EC2 roles through IMDSv2.
- `SMPLDOC_MAIL_SOURCE` and the S3 settings; `jobs` and `job` commands.
- Routing rules (from, to, subject, body, file name, format; review, hold, close, forward) with the old
  product's agree-or-conflict behaviour, saved-pattern screening, and evaluation in a time-limited
  subprocess. Job moves with the old product's transition table.
- Forwarding by SMTP (TLS required, certificate checked, password used only after TLS) to named forward
  targets only, with retries for temporary failures and none for permanent ones, size caps, and header
  and terminal-escape injection defences. Crash-safe: a queued forward survives a restart and is sent once.
- Commands: `rules`, `rule-add/enable/disable/delete`, `targets`, `target-add/delete`, `job-action`, `resolve`.
- **Changed:** a job now finishes as `ready` (a person decides) instead of `done`; `done` means forwarded.
  Step names are ingest, extract, rules, finish, deliver. Reprocessing replaces a job's values.
- `docs/ROUTING.md`.
- `deploy/aws/mail-intake.yaml` (SES rule, private bucket, least-privilege role), `deploy/aws/compose.yaml`
  and `docs/DEPLOY_AWS.md`.
- Hardened `Dockerfile` (digest-pinned base, non-root, health check) and example `compose.yaml`
  (read-only, no capabilities, loopback port, secret file). CI builds the image, scans it with
  Trivy and smoke-tests it with the same hardening flags.
