# Dev environment

- Needed now: **local only.** `docker compose up` (see README) runs the whole app, and `_auto:deploy` runs the same smoke test in CI. No cloud environment yet.
- Needed later: **yes, one thing.** The `aws-smoke` check (`_manual:ops`) needs a throwaway AWS
  account with SES in sandbox mode, one bucket and one small container. Everything else runs in
  Docker Compose.
- Revisit when the first adapter lands.
- Decided: 2026-11-12.
