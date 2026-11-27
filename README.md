# smpldoc Community Edition

Forward an email with documents. smpldoc reads it, pulls out the field values you care about, and
routes the job to where it should go.

It is a **self-hosted** service. It runs in your own cloud account, and your documents never reach
us.

> **Status: first code, no release yet.** The core job runner, the relay mail adapter, a SQLite
> store and a hardened container image exist and are tested. There is nothing to deploy for real
> yet. See [docs/FEATURES.md](docs/FEATURES.md) for what is built and planned. Watch or star the
> repository to follow progress.

## What it will be

- One container, with a disk and one bucket. SQLite on the disk is backed up to the bucket.
- Mail comes in through your own mail setup. On AWS, an SES rule writes each message into your
  bucket and the container reads it. A shared mailbox works too. No inbound port is needed for mail.
- Documents are read by an AI service you choose and pay for in your own account, or not at all.
- Each email becomes a job you can review, correct, route or forward.
- Each document becomes a **bundle** in a published, versioned format: the original, its text and
  where it sits on the page, the field values, and a short card that says what it is. AI agents
  read bundles through MCP. See [docs/ROADMAP.md](docs/ROADMAP.md).
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
