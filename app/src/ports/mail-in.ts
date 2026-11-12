// How incoming mail reaches the pipeline. An adapter reads a bucket folder or a mailbox.
// Delivery is at least once: a message that is not acknowledged comes back on the next poll.

/** What the source says about the sender. Anything that is not "pass" is held by the trust gate. */
export type SenderVerdict = "pass" | "fail" | "unknown";
export const SENDER_VERDICTS: readonly SenderVerdict[] = ["pass", "fail", "unknown"];

export interface InboundMail {
  /** Unique among messages the adapter has not finished with. */
  id: string;
  /** The message exactly as received. Never modified, never executed. */
  raw: Uint8Array;
  receivedAt: string;
  verdict: SenderVerdict;
}

export interface MailIn {
  /** Up to `max` pending messages, oldest first. Throws RangeError when max is below 1. */
  poll(max: number): Promise<InboundMail[]>;
  /** The message is done and is never returned again. Doing it twice is not an error. */
  ack(id: string): Promise<void>;
  /** Sets the message aside for review, with a reason. It is never returned again. */
  reject(id: string, reason: string): Promise<void>;
}
