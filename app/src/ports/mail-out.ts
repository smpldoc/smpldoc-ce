// How a finished job is forwarded by email. Validation lives here, once, so no adapter can
// forget it: a bad address or a header-injection attempt is refused before anything is sent.

export class InvalidMailError extends Error {}

export interface Attachment {
  filename: string;
  contentType: string;
  data: Uint8Array;
}

export interface OutboundMail {
  to: string[];
  subject: string;
  text: string;
  attachments?: Attachment[];
}

export interface MailOut {
  /** Sends the message and returns an id for it. Throws InvalidMailError before sending anything. */
  send(mail: OutboundMail): Promise<{ id: string }>;
}

const MAX_RECIPIENTS = 50;
const MAX_SUBJECT = 998;
const ADDRESS = /^[^\s@<>(),;:"\\]+@[^\s@<>(),;:"\\]+\.[^\s@<>(),;:"\\]+$/;
const LINE_BREAK = /[\r\n\u0000]/;
const FILENAME_FORBIDDEN = /[\r\n\u0000/\\]/;

export function assertValidOutbound(mail: OutboundMail): void {
  if (!Array.isArray(mail.to) || mail.to.length === 0) throw new InvalidMailError("at least one recipient is required");
  if (mail.to.length > MAX_RECIPIENTS) throw new InvalidMailError(`no more than ${MAX_RECIPIENTS} recipients`);
  for (const address of mail.to) {
    if (typeof address !== "string" || !ADDRESS.test(address)) throw new InvalidMailError("a recipient is not a plain email address");
  }
  if (typeof mail.subject !== "string" || LINE_BREAK.test(mail.subject)) throw new InvalidMailError("the subject must be a single line");
  if (mail.subject.length > MAX_SUBJECT) throw new InvalidMailError("the subject is too long");
  for (const attachment of mail.attachments ?? []) {
    if (!attachment.filename || FILENAME_FORBIDDEN.test(attachment.filename)) throw new InvalidMailError("an attachment name is not a plain file name");
    if (LINE_BREAK.test(attachment.contentType) || !attachment.contentType.includes("/")) throw new InvalidMailError("an attachment type is invalid");
  }
}
