# Dev environment

- Needed now: **no**. There is no code to run yet; checks run in GitHub Actions (`_auto:deploy`).
- Needed later: **yes, one thing.** The `aws-smoke` check (`_manual:ops`) needs a throwaway AWS
  account with SES in sandbox mode, one bucket and one small container. Everything else runs in
  Docker Compose.
- Revisit when the first adapter lands.
- Decided: 2026-11-12.
