/**
 * Product identity: one place for the name, definition and SEO copy, so the
 * page metadata, sign-in page and docs all describe DocuNexa AI the same way.
 *
 * Keep `formats` honest: only list a format as available once upload
 * accepts it (backend/app/services/document_service.py).
 */
export const PRODUCT = {
  name: "DocuNexa AI",
  tagline: "Enterprise Multimodal Document Intelligence Platform",
  definition:
    "DocuNexa AI is an enterprise multimodal document intelligence platform. It processes structured and unstructured documents using OCR, vision models, RAG and agentic AI, so you can search, understand, compare, summarize and extract information from documents with grounded citations.",
  /** Short sign-in page copy: the promise, not the feature list. */
  eyebrow: "Document intelligence for enterprise teams",
  pitch: "Ask anything across all your documents: reports, contracts, scans and registers. Get answers you can verify, down to the page.",
  /** ~155 characters: the length search engines show in results. */
  seoDescription:
    "DocuNexa AI is an enterprise document intelligence platform: ask questions across all your documents and get answers cited to the exact page.",
  keywords: [
    "document intelligence",
    "enterprise document AI",
    "multimodal RAG",
    "agentic AI",
    "OCR",
    "scanned PDF search",
    "contract analysis",
    "grounded citations",
  ],
  formats: {
    available: ["PDF", "Scanned PDF"],
    planned: ["Word", "Excel", "Images"],
  },
} as const;
