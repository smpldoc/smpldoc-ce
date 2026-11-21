# Security policy

smpldoc handles other people's email and documents, so it is built to be easy to inspect and hard
to misuse. This page says what it will never do, how to check a release, and how to report a
problem.

**Status: first code, no release yet.** The promises below are the rules every change must meet,
and the checks that enforce them are described under "How we enforce this". The container image is
built, scanned and smoke-tested on every pull request but not yet signed or published.

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

## If it is exposed to the internet by mistake

Assume someone will publish the port by accident. The design limits what that costs:

- **Mail is pulled, never pushed.** There is no inbound mail port to attack.
- **The only network surface today is `/healthz` and `/readyz`,** which return `{"status":"ok"}` and
  nothing else: no version, no counts, no names.
- **Closed by default.** The app binds `127.0.0.1` unless told otherwise. Any route that serves data
  is *protected*, and a protected route answers 401 unless a sign-in check says yes. With no sign-in
  configured it always answers 401.
- **It refuses to start open.** If you bind a non-loopback address and any protected route has no
  sign-in configured, the app exits (code 3) with a message instead of serving.
- **It tests itself.** After starting, the app calls each protected route with no credentials and
  exits if any answers. This catches a wiring mistake in a future release.
- **Typos fail loudly.** An unknown `SMPLDOC_*` setting is an error, so a misspelt safe setting
  never silently falls back.
- **Secrets stay out of sight.** The relay token is read from a file (`SMPLDOC_RELAY_TOKEN_FILE`) or
  the environment, is never logged or printed, and is sent only to the configured relay. Logs and
  step events hold ids, counts and error class names, never document text.
- **The container is locked down:** non-root user, read-only root filesystem, all Linux
  capabilities dropped, no new privileges, memory and process limits, a private data directory
  (mode 700), and the example compose file publishes the port on `127.0.0.1` only.

## If you read mail from S3 (Amazon SES)

- **No keys.** Use an ECS task role or an EC2 instance role. The container reads them from AWS's fixed
  link-local addresses (never from a setting), over IMDSv2 only, without following redirects.
- **Least privilege.** The stack's policy can list `inbox/`, read and delete in `inbox/`, and write to
  `processed/` and `quarantine/`. Nothing else.
- **Sender checks cannot be forged.** The verdict comes only from the topmost `Authentication-Results`
  header and only if it names SES. A header the sender wrote, or one lower down, is ignored.
- **Nothing is deleted outright**, and a listing that contains XML entity declarations is refused.

## Rules and forwarding

- **Forwarding goes only to named targets** an operator created. A rule or a command cannot name an
  arbitrary address, so a mistake or a hostile mail cannot send documents somewhere new.
- **Nothing from a mail can inject a header or an escape code.** Subjects, names and values are stripped of
  control characters before they go into an outgoing message or onto a terminal, and the SMTP client refuses
  a header that contains a line break.
- **SMTP needs TLS** (STARTTLS or implicit TLS, certificate and host name checked), and the password is sent
  only after TLS is up and never appears in an error. Plain text is allowed only to a server on this machine.
- **Rules cannot freeze the service.** Risky patterns are refused when saved, and evaluation runs in a
  separate process with a two-second limit.
- **A job is never lost to a rule or a mail-out problem:** it stays `ready` with the reason recorded.

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
