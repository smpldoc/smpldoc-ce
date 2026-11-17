# Configuration

Environment variables only. An unknown `SMPLDOC_*` name is an error, so a typo cannot leave a safe
default in place. Run `python -m smpldoc check-config` to validate without starting.

| Setting | Default | Meaning |
|---|---|---|
| `SMPLDOC_RELAY_URL` | none, required | The relay to pull mail from. `https` only (plain `http` on loopback for tests) |
| `SMPLDOC_RELAY_TOKEN_FILE` | none | File holding the relay token. Preferred. Use a Docker or Kubernetes secret |
| `SMPLDOC_RELAY_TOKEN` | none | The token itself. Set this or the `_FILE` form, not both |
| `SMPLDOC_DATA_DIR` | `/data` | SQLite file and stored documents. Created with mode 700 |
| `SMPLDOC_POLL_SECONDS` | `30` | Seconds between pulls (1 to 3600). Errors back off up to 8 times longer |
| `SMPLDOC_BATCH` | `10` | Messages per pull (1 to 100) |
| `SMPLDOC_BIND` | `127.0.0.1` | Listen address. The image sets `0.0.0.0` because only health checks are served |
| `SMPLDOC_PORT` | `8080` | Listen port |

## Commands

```bash
python -m smpldoc run                      # the default: pull, process, serve /healthz and /readyz
python -m smpldoc check-config             # validate settings, print nothing secret
python -m smpldoc add-company acme "Acme"  # a company's mail address is acme@<your domain>
```

Exit codes: 0 ok, 1 command failed, 2 bad usage or settings, 3 refused to start (exposure).

`/healthz` says the process is up. `/readyz` says a pull cycle finished recently, so it turns 503
while the relay is unreachable.
