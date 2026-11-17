# Feature register

One row per feature, so features are outlined first and built over time. A feature is **built**
only when its tests exist and pass. Statuses: `planned`, `building`, `built`.
New features start as a row here, then an issue, then a failing test.

| Id | Feature | Status | Tests | Notes |
|---|---|---|---|---|
| mail-in-relay | Pull mail from a relay | built | `tests/test_relay_pull.py` | Protocol: `RELAY_PROTOCOL.md` |
| mail-in-memory | In-memory mail source for tests and trials | built | `tests/test_adapters.py` | |
| store-sqlite | Jobs, documents, values, events on SQLite, scoped by company | built | `tests/test_adapters.py` | |
| blob-fs | Original documents on a local volume | built | `tests/test_adapters.py` | |
| extract-plain-text | Read `Name: value` lines from text | built | `tests/test_adapters.py` | PDFs and images need a real extractor |
| runner | ingest, extract, close with retries, step events, crash resume | built | `tests/test_runner.py` | |
| trust-gate | Hold anything whose sender verdict is not `pass` | built | `tests/test_runner.py` | |
| config | Settings from environment variables, secrets from files, typos are errors | built | `tests/test_config.py` | `CONFIG.md` |
| entrypoint | `python -m smpldoc` with run, check-config and add-company | built | `tests/test_main.py` | |
| health | `/healthz` and `/readyz` on a closed HTTP surface | built | `tests/test_http_exposure.py` | Public routes only |
| exposure-check | Refuse an open bind with unprotected routes; probe protected routes at start | built | `tests/test_http_exposure.py`, `tests/test_main.py` | Protected routes arrive with the portal |
| container | Hardened image and example compose file | building | `tests/test_container.py`, CI image job | Not yet signed or published |
| mail-in-s3 | Read mail SES wrote to a bucket | planned | | AWS bring-your-own mail |
| mail-in-imap | Read a mailbox | planned | | |
| mail-out | Forward a finished job (SES or SMTP) | planned | | |
| rules | Route a job by its values | planned | | Port from the private product |
| extract-bedrock | Read PDFs and images with an AI service | planned | | Optional, operator configured |
| portal | Web UI for jobs | planned | | Closed by default, OIDC required to bind beyond loopback |
| oidc | Sign-in through any OIDC provider | planned | | Recipes: Entra, Cognito, Okta, Clerk |
| mcp | MCP server | planned | | Read only by default, same OIDC tokens |
| container-release | Sign, SBOM and publish the image on a version tag | planned | | cosign, CycloneDX |
| deploy-aws | Deploy guide | planned | | First |
| deploy-cloudflare | Deploy guide | planned | | |
| deploy-azure | Deploy guide | planned | | Azure has no native inbound mail like SES: use the relay |
