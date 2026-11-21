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
- `deploy/aws/mail-intake.yaml` (SES rule, private bucket, least-privilege role), `deploy/aws/compose.yaml`
  and `docs/DEPLOY_AWS.md`.
- Hardened `Dockerfile` (digest-pinned base, non-root, health check) and example `compose.yaml`
  (read-only, no capabilities, loopback port, secret file). CI builds the image, scans it with
  Trivy and smoke-tests it with the same hardening flags.
