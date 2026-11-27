# Dev environment

- Needed now: **no**. The code is Python standard library only. Tests run in-process, with a fake
  relay on loopback, so `python -B -m unittest discover -s tests -t .` needs no cloud account.
- Needed later: **yes, one thing.** The `aws-smoke` check (`_manual:ops`) needs a throwaway AWS
  account with SES in sandbox mode, one bucket and one small container. Everything else runs in
  Docker Compose.
- Revisit when the `s3-inbox` adapter lands.
- Chapter 2 (bundles, OCR, MCP), checked 2026-11-27: still **no**. OCR uses tools inside the image;
  tests run in-process and in the CI image job. Blob-on-bucket tests use an in-process fake S3.
- Decided: 2026-11-12. Re-checked 2026-11-16 when the first adapters landed.
