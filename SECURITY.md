# Security policy

smpldoc handles other people's email and documents, so it is built to be easy to inspect and hard
to misuse. This page says what it will never do, how to check a release, and how to report a
problem.

**Status: design stage.** There is no release yet. The promises below are the rules every change
must meet, and the checks that enforce them are described under "How we enforce this".

## What smpldoc will never do

- **Send your documents to us.** Documents and extracted values stay in storage you own.
- **Phone home.** No usage data, no analytics, no update check. The container makes no outbound
  call except to a service you configured (your mail source, your AI service, your mail sender).
- **Update itself.** You choose when to upgrade.
- **Open a port for mail.** Mail arrives because the container reads a bucket or mailbox.
- **Run code from a message.** Attachments and mail bodies are data. They are parsed, never
  executed, and are not opened by anything that runs commands.
- **Store long-lived cloud keys** where a platform role can be used instead.
- **Run as root.** The image runs as a non-root user with a read-only filesystem and no extra Linux
  capabilities.

## How to check a release (from the first release)

Each release will publish:

- a container image signed with Sigstore `cosign`, pinned by digest (never use `latest`),
- an SBOM (CycloneDX) and a checksums file, each with a signature bundle,
- build provenance,
- release notes with the exact `cosign verify` command.

Verify the signature before you run an image. If it fails, do not run it, and tell us.

## How we enforce this

- Every GitHub Action is pinned to a full commit SHA, and every base image to a digest.
- Workflows default to read-only permissions and never use `pull_request_target`.
- CI fails on a committed secret, an unpinned dependency source, or a download piped to a shell.
- Pull requests run a vulnerability scan on the image once an image exists.
- OpenSSF Scorecard runs weekly and its result is public.
- Dependency updates arrive in small, reviewed pull requests. Security updates arrive as soon as
  they are published.

## Design limits you should know

- A single container cannot wall one internal component off from another the way separate
  services can. The code keeps those boundaries instead, and a build check fails if domain code
  imports a cloud library or an adapter.
- The portal binds to `127.0.0.1` by default. If you put it on a network, you are responsible for
  the proxy, TLS and who can reach it.

## Supported versions

Security fixes are made on the `main` branch and included in the next release. Run the latest
version.

## Reporting a vulnerability

Please do not report security vulnerabilities through public issues, discussions, or pull
requests.

Report them privately through GitHub:
**[Report a vulnerability](https://github.com/smpldoc/smpldoc-ce/security/advisories/new)**
(the **Security** tab, then **Report a vulnerability**).

Please include:

- A description of the issue and its impact.
- Steps to reproduce, or a proof of concept.
- The affected version or commit.

## What to expect

- We aim to acknowledge reports within 3 business days.
- We'll keep you updated while we investigate and fix the issue.
- We'll coordinate a disclosure date with you and credit you in the advisory, unless you'd rather
  stay anonymous.

Please give us reasonable time to release a fix before disclosing publicly.
