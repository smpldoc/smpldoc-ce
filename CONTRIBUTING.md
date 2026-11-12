# Contributing

Thanks for helping improve smpldoc Community Edition.

## Before you start

- For bugs and small fixes, open a pull request directly or file an issue first.
- For new features, adapters or larger changes, open an issue to discuss the idea before you write
  code.
- For security issues, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Project status

The project is at design stage. There is no application code yet, so the most useful
contributions now are reviews of `docs/ARCHITECTURE.md` and `SECURITY.md`.

## Checks

Run both before you push. CI runs the same checks.

```bash
python -B -m unittest discover -s scripts
python scripts/check_repo.py
cd app && npm test
```

`npm test` needs Node 22.18 or newer. There is nothing to install: the code has no dependencies
and Node runs the TypeScript directly.

## Rules this project holds itself to

- Tests first. Add a failing test, then the change.
- Pin everything. Every GitHub Action goes in as a full commit SHA with the version in a comment.
  Every base image goes in with a digest.
- No new runtime dependency without discussing it in an issue first.
- No telemetry, no self-update, no outbound call except to a service the operator configured.
- Never commit secrets, keys or personal data.
- Don't edit `reference/`. It is copied in by an automated pull request from the project's
  standards source.

## Pull requests

- Keep each pull request focused on one change.
- Add or update tests for behavior changes.
- Make sure CI is green.

By submitting a contribution, you agree it's licensed under the [Apache License 2.0](LICENSE).

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
