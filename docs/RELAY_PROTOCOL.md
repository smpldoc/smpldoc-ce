# Relay protocol (v1 draft)

How the container pulls mail from a relay. The relay can be the hosted service or anything that
speaks this protocol, so anyone can run their own. The client is `smpldoc/adapters/relay_pull.py`;
`tests/fake_relay.py` is a minimal server, and the shared `MailIn` contract tests pin the behaviour.

## Why pull

The container only makes outbound requests. It opens no inbound port for mail, so a container that
is exposed to the internet by mistake still has no mail endpoint to attack.

## Rules for the client

- The relay URL must be `https`. Plain `http` is accepted only for loopback, for local tests.
- Every request carries `Authorization: Bearer <token>`. The token is sent to the configured relay
  only. Redirects are never followed, so the token cannot be forwarded elsewhere.
- Responses are size-capped (25 MB for a raw message by default) and every request has a timeout.
- The relay's verdict is one of `pass`, `fail`, `unknown`. Anything else is read as `unknown`.
  Anything that is not `pass` is held, never extracted.

## Calls

| Call | Meaning | Answer |
|---|---|---|
| `GET /v1/messages?limit=N&lease=S` | Hand out up to N (1 to 100) messages and hide them for S seconds | `200 {"messages":[{"id","receipt","sender","recipient","verdict","size"}]}` |
| `GET /v1/messages/{receipt}/raw` | The exact raw message | `200 message/rfc822` bytes |
| `POST /v1/messages/{receipt}/ack` | Done with it. The relay deletes it | `204` |
| `POST /v1/messages/{receipt}/nack` | Give it back to be delivered again | `204` |

`401` or `403` means the token is wrong. An unacked message comes back after its lease runs out,
so a crash never loses mail. Receipts are opaque and URL-quoted by the client.

## What the hosted relay adds (private service, not in this repo)

Email Routing catch-all, a per-company queue, sign-up, and a free tier of 100 emails a day. Over the
limit, mail is rejected at receive time. The relay keeps a message only until it is acked or
its retention window passes.
