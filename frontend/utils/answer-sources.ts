import type { Citation } from "@/types";

export interface AnswerSource {
  documentId: string;
  title: string;
  versions: string[];
  /** Citation numbers ([n]) that point into this document. */
  indexes: number[];
  pages: number[];
  /** Other documents that hold the same text as what was cited here. */
  alsoFoundIn: { documentId: string; title: string }[];
}

/** The documents an answer drew on, in the order they are first cited. */
export function answerSources(citations: Citation[]): AnswerSource[] {
  const byDocument = new Map<string, AnswerSource>();
  for (const c of [...citations].sort((a, b) => a.index - b.index)) {
    const source = byDocument.get(c.documentId) ?? {
      documentId: c.documentId,
      title: c.documentTitle || "Untitled document",
      versions: [],
      indexes: [],
      pages: [],
      alsoFoundIn: [],
    };
    if (c.version && !source.versions.includes(c.version)) source.versions.push(c.version);
    if (!source.indexes.includes(c.index)) source.indexes.push(c.index);
    if (c.page && !source.pages.includes(c.page)) source.pages.push(c.page);
    for (const other of c.alsoFoundIn ?? []) {
      if (!source.alsoFoundIn.some((o) => o.documentId === other.documentId)) source.alsoFoundIn.push(other);
    }
    byDocument.set(c.documentId, source);
  }
  for (const s of byDocument.values()) {
    s.pages.sort((a, b) => a - b);
    // A document already listed as a source isn't repeated as "also found in".
    s.alsoFoundIn = s.alsoFoundIn.filter((o) => !byDocument.has(o.documentId));
  }
  return [...byDocument.values()];
}
