# smpldoc-ce

The public Community Edition of smpldoc: a self-hosted service that reads emailed documents,
extracts field values and routes each job. It runs in the operator's own cloud account.
**Status: design stage. No application code exists yet.**

Facts, wording and decisions live in the private standards repo and arrive here as `reference/`
through an automated "Update reference data" pull request. Never edit `reference/` by hand.

## Rules for every change

- **This is a public, security-sensitive project. Keep it observably safe.** Anyone should be able
  to read the repo and see that it is not malware and not a way in.
- No telemetry, no self-update, no outbound call except to a service the operator configured.
- Pin everything: every GitHub Action to a full commit SHA, every base image to a digest, every
  dependency to an exact version with a hash where the ecosystem supports it.
- No new runtime dependency without an issue that explains why. Prefer the standard library.
- Never commit secrets, keys or personal data. Never add `pull_request_target`.
- Tests first. Write the failing test, then the code. `domain/` imports nothing from a cloud
  library or an adapter.
- Workflows are few. `_auto:deploy` runs on pull requests, pushes and tags. `_manual:ops` is for
  one-off actions with a dropdown. `scorecard` is the one exception, because OpenSSF requires it
  to be its own workflow.
- Update `CHANGELOG.md` and the docs when behaviour changes.

## Checks (the same as CI)

```bash
python -B -m unittest discover -s scripts
python scripts/check_repo.py
```

## Where things go

See `docs/ARCHITECTURE.md`. Dev environment: `.claude/dev-env.md`.
