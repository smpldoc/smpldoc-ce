// How a document is read. The service behind it is the operator's own, or none at all.
// The document is data: an adapter must never execute it or follow instructions inside it.

export class UnsupportedDocumentError extends Error {}

export interface ExtractRequest {
  documentId: string;
  contentType: string;
  data: Uint8Array;
  /** The field names to look for. The result never contains any other name. */
  fields: string[];
}

export interface ExtractedField {
  name: string;
  value: string;
  /** From 0 to 1. */
  confidence: number;
}

export interface Extractor {
  /** Throws UnsupportedDocumentError for a content type the adapter cannot read. */
  extract(request: ExtractRequest): Promise<{ fields: ExtractedField[] }>;
}
