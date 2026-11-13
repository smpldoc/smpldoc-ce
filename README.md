# smpldoc Community Edition

Forward an email with documents. smpldoc reads it, pulls out the field values you care about, and
routes the job to where it should go.

It is a **self-hosted** service. It runs in your own cloud account, and your documents never reach
us.

> **Status: early build, not released.** The pipeline runs end to end in one container on your
> machine: it reads mail from an inbox folder, makes a job, extracts values from plain-text
> documents, and serves a password-protected portal. S3 and SES, a real AI service, PDF reading
> and a signed release are not built yet. Nothing here is ready for production mail.

## Try it locally

Needs Docker with Compose v2.

```bash
git clone https://github.com/smpldoc/smpldoc-ce.git
cd smpldoc-ce
SMPLDOC_ADMIN_TOKEN='choose-a-long-password' docker compose up -d --build
```

Open <http://127.0.0.1:3787> and sign in with any user name and that password. Drop a raw email
(`.eml`) into the inbox folder inside the volume:

```bash
docker compose exec -T smpldoc sh -c 'mkdir -p /data/blob/inbox && cat > /data/blob/inbox/first' < message.eml
```

It becomes a job within a few seconds. Plain-text lines such as `invoice_number: 1042` are read as
values. Run `./scripts/smoke-local.sh` to check the whole path automatically.

## What it will be

- One container, with a disk and one bucket. SQLite on the disk is backed up to the bucket.
- Mail comes in through your own mail setup. On AWS, an SES rule writes each message into your
  bucket and the container reads it. A shared mailbox works too. No inbound port is needed for mail.
- Documents are read by an AI service you choose and pay for in your own account, or not at all.
- Each email becomes a job you can review, correct, route or forward.
- Free and open source under Apache-2.0.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why you can trust it

smpldoc handles other people's email, so the rules are strict and the repository enforces them in
public:

- No telemetry, no self-update, no outbound call except to a service you configured.
- Runs as a non-root user with a read-only filesystem and no extra capabilities.
- Every release is signed, ships with an SBOM, and is pinned by digest.
- Every GitHub Action and base image is pinned, and CI fails on a committed secret.

Read [SECURITY.md](SECURITY.md) for the full list, how to verify a release, and how to report a
problem.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Right now the most useful help is review of the
architecture and security documents.

## License

[Apache-2.0](LICENSE).
