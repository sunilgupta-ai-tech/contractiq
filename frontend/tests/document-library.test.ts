import { afterEach, describe, expect, it, vi } from "vitest";
import { toDocument, type ApiDocument } from "@/lib/adapters";

const base: ApiDocument = {
  id: "d1",
  title: "Invoice September",
  contract_type: "OTHER",
  counterparty: null,
  status: "COMPLETED",
  effective_date: null,
  expiry_date: null,
  tags: [],
  latest_version: {
    id: "v1",
    label: "v1",
    original_filename: "invoice.jpg",
    page_count: 1,
    size_bytes: 500,
    is_scanned: null,
    status: "COMPLETED",
    error_message: null,
    created_at: "2026-09-25T00:00:00Z",
  },
  updated_at: "2026-09-25T00:00:00Z",
};

describe("library adapters", () => {
  it("maps file type and file name", () => {
    const doc = toDocument({ ...base, file_type: "IMAGE" });
    expect([doc.fileType, doc.fileName]).toEqual(["IMAGE", "invoice.jpg"]);
  });

  it("maps visibility and injection flags (Phase 20)", () => {
    const doc = toDocument({
      ...base,
      visibility: "RESTRICTED",
      latest_version: { ...base.latest_version!, injection_flags: 2 },
    });
    expect([doc.visibility, doc.injectionFlags]).toEqual(["RESTRICTED", 2]);
    expect(toDocument(base).visibility).toBe("ORGANIZATION");
  });

  it("treats documents from before file types as PDFs named by title", () => {
    const doc = toDocument({ ...base, latest_version: null });
    expect([doc.fileType, doc.fileName]).toEqual(["PDF", "Invoice September"]);
  });
});

describe("library requests", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.doUnmock("@/lib/api-client");
  });

  async function service(response: unknown) {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_USE_DEMO_DATA", "false");
    const apiRequest = vi.fn().mockResolvedValue(response);
    vi.doMock("@/lib/api-client", () => ({ apiRequest }));
    const { documentService } = await import("@/services/document-service");
    return { documentService, apiRequest };
  }

  it("sends type, statuses, search, sort and page to the server", async () => {
    const { documentService, apiRequest } = await service({ items: [{ ...base, file_type: "IMAGE" }], total: 120 });
    const page = await documentService.library({
      fileType: "IMAGE",
      status: "processing",
      q: "  invoice ",
      sort: "name",
      offset: 50,
      limit: 50,
    });
    const url = new URL(apiRequest.mock.calls[0]![0] as string, "http://x");
    expect(url.pathname).toBe("/documents");
    expect(url.searchParams.getAll("status")).toContain("EMBEDDING");
    expect(url.searchParams.getAll("status")).not.toContain("COMPLETED");
    expect(Object.fromEntries([...url.searchParams].filter(([k]) => k !== "status"))).toEqual({
      q: "invoice",
      file_type: "IMAGE",
      sort: "name",
      offset: "50",
      limit: "50",
    });
    expect([page.total, page.items[0]!.fileType]).toEqual([120, "IMAGE"]);
  });

  it("asks for every type on the All tab and fills missing counts", async () => {
    const { documentService, apiRequest } = await service({ all: 3, by_file_type: { PDF: 2, EXCEL: 1 } });
    const counts = await documentService.libraryCounts({ status: "all", q: "" });
    expect(apiRequest.mock.calls[0]![0]).toBe("/documents/facets?");
    expect(counts).toEqual({ ALL: 3, PDF: 2, IMAGE: 0, WORD: 0, EXCEL: 1 });
  });
});
