// A small, forgiving reader for raw email (RFC 5322 and MIME). It never throws, never runs
// anything, and caps how much of a message it will unpack, so a hostile message cannot make it
// do unbounded work. Pure: it imports nothing.

export const MAX_PARTS = 50;
export const MAX_DEPTH = 5;

export interface MessagePart {
  /** Lower case, without parameters, for example "application/pdf". */
  contentType: string;
  filename: string | null;
  isAttachment: boolean;
  /** The decoded bytes. */
  data: Uint8Array;
}

export interface ParsedMessage {
  messageId: string | null;
  subject: string;
  from: string;
  /** Header name (lower case) to every value, in the order they appear. */
  headers: Record<string, string[]>;
  parts: MessagePart[];
}

function toBinary(raw: Uint8Array): string {
  let out = "";
  for (let i = 0; i < raw.length; i += 8192) out += String.fromCharCode(...raw.subarray(i, i + 8192));
  return out;
}

function fromBinary(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i) & 255;
  return out;
}

function splitHeadBody(text: string): { head: string; body: string } {
  const match = /\r?\n\r?\n/.exec(text);
  if (match) return { head: text.slice(0, match.index), body: text.slice(match.index + match[0].length) };
  // No blank line: a message that is all headers, or no headers. Treat a header-looking start as headers.
  return /^[!-9;-~]+:/.test(text) ? { head: text, body: "" } : { head: "", body: text };
}

function parseHeaders(head: string): Record<string, string[]> {
  const unfolded = head.replace(/\r?\n[ \t]+/g, " ");
  const headers: Record<string, string[]> = {};
  for (const line of unfolded.split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon < 1) continue;
    const name = line.slice(0, colon).trim().toLowerCase();
    if (!/^[!-9;-~]+$/.test(name)) continue;
    (headers[name] ??= []).push(line.slice(colon + 1).trim());
  }
  return headers;
}

function decodeBytes(data: Uint8Array, charset: string): string {
  try {
    return new TextDecoder(charset.toLowerCase()).decode(data);
  } catch {
    return new TextDecoder("utf-8").decode(data);
  }
}

function decodeQuotedPrintable(text: string, wordMode = false): Uint8Array {
  const source = wordMode ? text.replace(/_/g, " ") : text.replace(/=\r?\n/g, "");
  const out: number[] = [];
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (c === "=" && /^[0-9A-Fa-f]{2}$/.test(source.slice(i + 1, i + 3))) {
      out.push(parseInt(source.slice(i + 1, i + 3), 16));
      i += 2;
    } else out.push(source.charCodeAt(i) & 255);
  }
  return Uint8Array.from(out);
}

function decodeBase64(text: string): Uint8Array {
  try {
    return fromBinary(atob(text.replace(/[^A-Za-z0-9+/=]/g, "")));
  } catch {
    return fromBinary(text);
  }
}

export function decodeWords(value: string): string {
  return value.replace(/=\?([^?\s]+)\?([bBqQ])\?([^?\s]*)\?=/g, (_m, charset: string, enc: string, payload: string) =>
    decodeBytes(enc.toLowerCase() === "b" ? decodeBase64(payload) : decodeQuotedPrintable(payload, true), charset),
  );
}

function parameter(header: string, name: string): string | null {
  const match = new RegExp(`;\\s*${name}\\s*=\\s*(?:"([^"]*)"|([^;\\s]*))`, "i").exec(header);
  return match ? (match[1] ?? match[2] ?? "") : null;
}

function mediaType(header: string | undefined): string {
  return (header ?? "text/plain").split(";")[0].trim().toLowerCase() || "text/plain";
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function collect(headers: Record<string, string[]>, body: string, depth: number, parts: MessagePart[]): void {
  if (parts.length >= MAX_PARTS) return;
  const contentType = headers["content-type"]?.[0];
  const type = mediaType(contentType);
  const boundary = parameter(contentType ?? "", "boundary");
  if (type.startsWith("multipart/") && boundary) {
    if (depth >= MAX_DEPTH) return;
    const marker = new RegExp(`(?:^|\\r?\\n)--${escapeRegExp(boundary)}(--)?[ \\t]*(?=\\r?\\n|$)`, "g");
    const marks = [...body.matchAll(marker)];
    for (let i = 0; i < marks.length && parts.length < MAX_PARTS; i++) {
      if (marks[i][1]) break;
      const start = marks[i].index + marks[i][0].length;
      const end = i + 1 < marks.length ? marks[i + 1].index : body.length;
      const { head, body: inner } = splitHeadBody(body.slice(start, end).replace(/^\r?\n/, ""));
      collect(parseHeaders(head), inner, depth + 1, parts);
    }
    return;
  }
  const encoding = (headers["content-transfer-encoding"]?.[0] ?? "7bit").trim().toLowerCase();
  const data = encoding === "base64" ? decodeBase64(body) : encoding === "quoted-printable" ? decodeQuotedPrintable(body) : fromBinary(body);
  const disposition = headers["content-disposition"]?.[0] ?? "";
  const filename = parameter(disposition, "filename") ?? parameter(contentType ?? "", "name");
  parts.push({
    contentType: type,
    filename: filename ? decodeWords(filename) : null,
    isAttachment: /^\s*attachment/i.test(disposition),
    data,
  });
}

export function parseMessage(raw: Uint8Array): ParsedMessage {
  const { head, body } = splitHeadBody(toBinary(raw));
  const headers = parseHeaders(head);
  const parts: MessagePart[] = [];
  collect(headers, body, 0, parts);
  return {
    messageId: headers["message-id"]?.[0]?.trim() || null,
    subject: decodeWords(headers["subject"]?.[0] ?? ""),
    from: decodeWords(headers["from"]?.[0] ?? ""),
    headers,
    parts,
  };
}
