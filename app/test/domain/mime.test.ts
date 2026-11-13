import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseMessage } from "../../src/domain/mime.ts";
import { bytes, text } from "../helpers.ts";

const crlf = (lines: string[]) => bytes(lines.join("\r\n"));

describe("parseMessage", () => {
  it("reads the main headers and a plain body", () => {
    const m = parseMessage(crlf(["From: A <a@x.test>", "Subject: Hello", "Message-ID: <m1@x.test>", "Content-Type: text/plain; charset=utf-8", "", "invoice_number: 1042"]));
    assert.equal(m.messageId, "<m1@x.test>");
    assert.equal(m.subject, "Hello");
    assert.equal(m.from, "A <a@x.test>");
    assert.equal(m.parts.length, 1);
    assert.equal(m.parts[0].contentType, "text/plain");
    assert.equal(text(m.parts[0].data), "invoice_number: 1042");
  });

  it("accepts bare line feeds and unfolds long headers", () => {
    const m = parseMessage(bytes("Subject: one\n two\n\tthree\nMessage-ID: <a@b>\n\nbody"));
    assert.equal(m.subject, "one two three");
    assert.equal(text(m.parts[0].data), "body");
  });

  it("decodes encoded-word subjects", () => {
    assert.equal(parseMessage(bytes("Subject: =?utf-8?B?RmFrdHVyYQ==?=\n\nx")).subject, "Faktura");
    assert.equal(parseMessage(bytes("Subject: =?utf-8?Q?Caf=C3=A9_menu?=\n\nx")).subject, "Café menu");
  });

  it("splits multipart mail and decodes base64 and quoted-printable parts", () => {
    const raw = crlf([
      "Message-ID: <mp@x>", 'Content-Type: multipart/mixed; boundary="BOUND"', "",
      "preamble ignored", "--BOUND", "Content-Type: text/plain", "Content-Transfer-Encoding: quoted-printable", "", "total=3D99",
      "--BOUND", 'Content-Type: text/plain; name="inv.txt"', 'Content-Disposition: attachment; filename="inv.txt"', "Content-Transfer-Encoding: base64", "", "dG90YWw6IDk5",
      "--BOUND", "Content-Type: application/pdf", 'Content-Disposition: attachment; filename="a.pdf"', "Content-Transfer-Encoding: base64", "", "JVBERg==",
      "--BOUND--", "epilogue ignored", "",
    ]);
    const m = parseMessage(raw);
    assert.equal(m.parts.length, 3);
    assert.equal(text(m.parts[0].data), "total=99");
    assert.equal(m.parts[0].filename, null);
    assert.deepEqual([m.parts[1].filename, m.parts[1].isAttachment, text(m.parts[1].data)], ["inv.txt", true, "total: 99"]);
    assert.deepEqual([m.parts[2].contentType, m.parts[2].filename], ["application/pdf", "a.pdf"]);
    assert.deepEqual([...m.parts[2].data], [0x25, 0x50, 0x44, 0x46]);
  });

  it("flattens nested multipart parts", () => {
    const raw = crlf([
      'Content-Type: multipart/mixed; boundary="O"', "", "--O", 'Content-Type: multipart/alternative; boundary="I"', "",
      "--I", "Content-Type: text/plain", "", "plain", "--I", "Content-Type: text/html", "", "<b>html</b>", "--I--", "--O--", "",
    ]);
    assert.deepEqual(parseMessage(raw).parts.map((p) => p.contentType), ["text/plain", "text/html"]);
  });

  it("never throws on junk, empty input or a missing blank line", () => {
    for (const junk of [new Uint8Array(), bytes("no headers at all"), bytes("Subject: x"), Uint8Array.from([0, 255, 254, 10, 10, 0])]) {
      const m = parseMessage(junk);
      assert.ok(Array.isArray(m.parts));
      assert.equal(typeof m.subject, "string");
    }
  });

  it("does not follow a tiny message into a bomb: part count and nesting are capped", () => {
    const many = ["Content-Type: multipart/mixed; boundary=B", "", ...Array.from({ length: 500 }, () => ["--B", "Content-Type: text/plain", "", "x"]).flat(), "--B--", ""];
    assert.ok(parseMessage(crlf(many)).parts.length <= 50);
    let nested = "x";
    for (let i = 0; i < 40; i++) nested = `Content-Type: multipart/mixed; boundary=B${i}\r\n\r\n--B${i}\r\n${nested}\r\n--B${i}--\r\n`;
    assert.doesNotThrow(() => parseMessage(bytes(nested)));
  });

  it("treats a message-id or subject with hostile text as plain text", () => {
    const m = parseMessage(bytes("Subject: <script>alert(1)</script>\nMessage-ID: <a@b>\n\n"));
    assert.equal(m.subject, "<script>alert(1)</script>");
  });
});
