// In-memory Extractor. Reads plain text lines like "invoice_number: 1042". It is a test double
// and a stand-in for "no AI service": it never calls anything and never runs the document.
import type { ExtractedField, Extractor } from "../../ports/extractor.ts";
import { UnsupportedDocumentError } from "../../ports/extractor.ts";

const LINE = /^([a-z][a-z0-9_]*):[ \t]*(.*?)[ \t]*$/;

export function createMemoryExtractor(): Extractor {
  return {
    async extract(request) {
      if (request.contentType !== "text/plain") throw new UnsupportedDocumentError(`${request.contentType} is not supported`);
      const wanted = new Set(request.fields);
      const found = new Map<string, ExtractedField>();
      for (const line of new TextDecoder().decode(request.data).split(/\r?\n/)) {
        const match = LINE.exec(line);
        if (match && wanted.has(match[1]) && !found.has(match[1])) {
          found.set(match[1], { name: match[1], value: match[2], confidence: 1 });
        }
      }
      return { fields: [...found.values()] };
    },
  };
}
