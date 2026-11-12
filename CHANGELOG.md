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
- The five ports (`BlobStore`, `MailIn`, `MailOut`, `Extractor`, `Store`) and the job workflow
  rules, with one shared contract test suite per port. Every adapter must pass its suite.
- Reference adapters that pass the suites: in-memory versions of all five ports, and a filesystem
  `BlobStore` that refuses keys and symbolic links that lead outside its folder.
- Boundary tests: the domain imports nothing, ports import only the domain, only adapters use
  Node modules, and `package.json` declares no dependencies.
- `npm test` runs in `_auto:deploy` on Node 22.23.4.
