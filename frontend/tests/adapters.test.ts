import { describe, expect, it } from "vitest";
import {
  toAnswer,
  toComparisonRow,
  toDetail,
  toDocument,
  toKeyDates,
  toRiskFinding,
  worstRisk,
  type ApiDocument,
  type ApiRiskFinding,
} from "@/lib/adapters";
import { queued } from "@/lib/analysis-queue";

const version = {
  id: "v2",
  label: "v2",
  page_count: 12,
  size_bytes: 2048,
  is_scanned: false,
  status: "COMPLETED" as const,
  error_message: null,
  created_at: "2026-09-01T10:00:00Z",
};

const apiDoc: ApiDocument = {
  id: "d1",
  title: "Acme MSA",
  contract_type: "MSA",
  counterparty: null,
  status: "COMPLETED",
  effective_date: "2026-01-01",
  expiry_date: null,
  tags: ["vendor"],
  latest_version: version,
  version_count: 2,
  updated_at: "2026-09-02T10:00:00Z",
};

const finding = (topic: string, severity: ApiRiskFinding["severity"], missing = false): ApiRiskFinding => ({
  id: `f-${topic}`,
  rule: "rule",
  title: "Automatic renewal",
  severity,
  topic,
  rationale: "Renews unless notice is given.",
  missing,
  document_id: "d1",
  document_title: "Acme MSA",
  clause: missing ? null : "3.1",
  page: missing ? null : 2,
  excerpt: missing ? null : "shall automatically renew",
  status: "open",
});

describe("document adapters", () => {
  it("maps the list shape and fills defaults", () => {
    const doc = toDocument(apiDoc);
    expect(doc).toMatchObject({
      id: "d1",
      counterparty: "—",
      contractType: "MSA",
      progress: 100,
      pages: 12,
      sizeBytes: 2048,
      version: "v2",
      riskLevel: null,
    });
    expect(doc.versions).toEqual([{ id: "v2", label: "v2", uploadedAt: version.created_at, pages: 12, status: "COMPLETED" }]);
  });

  it("builds the detail view from analysis, marking clause risk by topic", () => {
    const detail = toDetail(apiDoc, {
      clauses: [
        { topic: "auto_renewal", label: "Automatic renewal", found: true, quote: "renews", clause: "3.1", page: 2, evidence: { section: "3", section_title: "RENEWAL" } },
        { topic: "indemnity", label: "Indemnity", found: false, quote: null, clause: null, page: null, evidence: null },
      ],
      keyTerms: [{ label: "Non-renewal notice", value: "90 days", clause: "3.1", page: 2 }],
      findings: [finding("auto_renewal", "medium"), finding("liability_cap", "high", true)],
    });
    expect(detail.clauses).toEqual([
      { id: "auto_renewal", number: "3.1", title: "Automatic renewal", section: "RENEWAL", page: 2, text: "renews", risk: "medium" },
    ]);
    expect(detail.keyTerms[0]).toEqual({ label: "Non-renewal notice", value: "90 days", clause: "3.1", page: 2 });
    expect([detail.riskLevel, detail.riskCount]).toEqual(["high", 2]);
    // Findings link to their clause; a missing protective clause has none.
    expect(detail.findings?.map((f) => [f.severity, f.clauseId])).toEqual([
      ["medium", "auto_renewal"],
      ["high", undefined],
    ]);
    expect(toDetail(apiDoc, null).clauses).toEqual([]);
  });

  it("picks the worst severity", () => {
    expect(worstRisk([])).toBeNull();
    expect(worstRisk([{ severity: "low" }, { severity: "high" }, { severity: "medium" }])).toBe("high");
  });
});

describe("answer and analysis adapters", () => {
  it("maps a query response, preferring groundedness", () => {
    const answer = toAnswer({
      id: "m1",
      question: "Notice?",
      answer: "60 days [1].",
      citations: [{ index: 1, chunk_id: "c9", document_id: "d1", document_title: null, version_label: "v2", page: 12, section: "8", section_title: "Termination", clause: "8.3", quote: "sixty (60) days", score: 1.2 }],
      steps: [{ key: "retrieve", label: "Hybrid search", detail: "20 candidates", duration_ms: 41, status: "done" }],
      cited_fraction: 0.5,
      groundedness: 1,
      model: "gemini-2.5-flash",
      latency_ms: 1800,
    });
    expect(answer.citations[0]).toMatchObject({ id: "c9-1", documentTitle: "", section: "Termination", clause: "8.3", version: "v2" });
    expect(answer.steps[0]).toEqual({ key: "retrieve", label: "Hybrid search", detail: "20 candidates", durationMs: 41, status: "done" });
    expect([answer.groundedness, answer.latencyMs, answer.model]).toEqual([1, 1800, "gemini-2.5-flash"]);
  });

  it("explains missing-clause findings", () => {
    const missing = toRiskFinding(finding("liability_cap", "high", true));
    expect(missing).toMatchObject({ clause: "—", page: 0, excerpt: "No such clause was found in this contract.", status: "open", missing: true });
    expect(toRiskFinding(finding("auto_renewal", "medium")).excerpt).toBe("shall automatically renew");
  });

  it("maps comparison rows and drops start dates from deadlines", () => {
    const row = toComparisonRow({
      label: "Termination notice",
      diff: "changed",
      note: "Notice days: 30 → 60.",
      left: { clause: "8.3", page: 23, text: "thirty (30) days" },
      right: { clause: null, page: null, text: "sixty (60) days" },
      risk: null,
    });
    expect(row).toEqual({
      topic: "Termination notice",
      diff: "changed",
      note: "Notice days: 30 → 60.",
      left: { clause: "8.3", page: 23, text: "thirty (30) days" },
      right: { clause: "—", page: 0, text: "sixty (60) days" },
      risk: undefined,
    });
    const dates = toKeyDates([
      { date: "2025-01-01", label: "Effective date", kind: "start", document_title: "MSA" },
      { date: "2026-10-02", label: "Non-renewal notice deadline", kind: "notice", document_title: "MSA" },
    ]);
    expect(dates).toEqual([{ date: "2026-10-02", label: "Non-renewal notice deadline", kind: "notice", documentTitle: "MSA" }]);
  });
});

describe("analysis queue", () => {
  it("runs requests one at a time, and a failure doesn't block the next", async () => {
    const order: string[] = [];
    const slow = queued(async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push("first");
      throw new Error("boom");
    });
    const next = queued(async () => {
      order.push("second");
      return 2;
    });
    await expect(slow).rejects.toThrow("boom");
    await expect(next).resolves.toBe(2);
    expect(order).toEqual(["first", "second"]);
  });
});
