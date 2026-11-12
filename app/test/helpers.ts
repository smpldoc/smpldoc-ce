import type { Clock } from "../src/ports/store.ts";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export const bytes = (text: string): Uint8Array => encoder.encode(text);
export const text = (data: Uint8Array | null): string | null => (data === null ? null : decoder.decode(data));

/** A clock that moves one second on every call, so ordering is always predictable. */
export function fakeClock(): Clock {
  let tick = 0;
  return () => new Date(Date.UTC(2026, 0, 1, 0, 0, tick++)).toISOString();
}
