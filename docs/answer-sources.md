# Which document an answer comes from (Phase 25)

When a question is asked across the whole library (no documents selected), the
same information is often in several documents. "What is Python?" may be
answered by a training guide, an onboarding handbook and an IT policy. This page
explains how DocuNexa AI picks the evidence, how it tells the user where the
answer came from, and why the result is the same for finance, education, HR or
any other kind of document.

## The pipeline

```
question
   │
   ├─ 1. Scope ............ organization only, documents the user may see,
   │                        latest version of each document
   ├─ 2. Hybrid search .... meaning (dense vectors, top 40)
   │                        + exact words (BM25 keywords, top 40)
   │                        fused with Reciprocal Rank Fusion → 20 candidates
   ├─ 3. Rerank ........... score every candidate (see below)
   ├─ 4. Select evidence .. merge repeated text, share slots between
   │                        documents, newest upload wins exact ties → top 6
   ├─ 5. Answer ........... the model answers only from those 6, citing [n]
   └─ 6. Check ............ groundedness of every cited sentence
```

Steps 1–3, 5 and 6 are described in [rag.md](rag.md) and
[agentic-rag.md](agentic-rag.md). Step 4 is new in Phase 25.

### Step 3: reranking score

```
score = 1.0 × position after fusion      (higher = found earlier)
      + 1.5 if the question names a clause the chunk contains ("clause 8.3")
      + 0.6 × share of the question's words in the chunk's headings
      + 0.3 × share of the question's words in the chunk's text
```

The document that "wins" is the one whose passage matches the question best. The
system does not judge which document is more official or more correct.

### Step 4: selecting the evidence (`app/rag/selection.py`)

Three rules decide which 6 passages the model sees. None of them calls a model,
so they cost **no tokens**. The evidence budget (`CONTEXT_MAX_TOKENS`, 6,000
tokens) and the number of passages (`RERANK_TOP_N`, 6) are unchanged.

| Rule | What it does | Why |
|---|---|---|
| **Repeated text is merged** | A passage is dropped only when every word and number in it already appears, in the same order, inside a passage that is kept. Its document is recorded as "also found in". | The same definition copied into five handbooks would otherwise fill five of the six slots. The freed slots go to the next different evidence. |
| **One document's share** | One document takes at most 3 slots (`EVIDENCE_MAX_PER_DOCUMENT`) while other documents have relevant passages. With nothing else relevant, it fills the remaining slots after all. | A long document cannot crowd out every other document. |
| **Newest upload wins exact ties** | Only passages with exactly the same score swap places; newer uploads come first. | When two documents match equally well, the more recent one is usually the current one. |

#### Different content is never dropped

The merge rule is deliberately strict. Two passages count as repeats only if the
smaller one is **wholly contained** in the larger one: every word and every
number. Any difference keeps both:

| Domain | Passage A | Passage B | Result |
|---|---|---|---|
| Finance | Invoice 4471 … Amount due: Rs 18,500 | Invoice 4471 … Amount due: Rs 18,600 | both kept |
| Education | Course CS101 covers variables and loops | Course CS102 covers variables and loops | both kept |
| HR / policy | Attendance is mandatory | Attendance is not mandatory | both kept |
| Any | "Python is a programming language." | The same sentence inside a longer section | the longer one kept, the sentence's document listed as "also found in" |

Capitalisation, punctuation, line breaks and spacing are ignored when comparing,
because they differ between copies of the same text. Words and numbers are not.

If the documents disagree, the model is instructed to say so and cite each one.

## What the user sees

Under every answer in the Assistant:

```
The amount due on invoice 4471 is Rs 18,500 [1][2]. The amount due on
invoice 5120 is Rs 9,200 [3].

SOURCES · 2 DOCUMENTS
📄 invoice-4471   v1  p.1   [1] [2]
📄 invoice-5120   v1  p.1   [3]
```

For repeated text:

```
SOURCE
📄 Python Training Guide   v2  p.3   [1]
   Same text also in: Onboarding Handbook, IT Policy 2026 (+2 more)
```

Each document name opens the document; each `[n]` highlights the cited passage
in the Evidence panel. The agent trace shows how many repeated passages were
merged ("top 6 (heuristic), 2 repeated passages merged").

## API

`POST /query` citations carry one new field (default empty, so existing clients
are unaffected):

```json
{
  "index": 1,
  "document_id": "…",
  "document_title": "Python Training Guide",
  "also_found_in": [
    {"document_id": "…", "document_title": "Onboarding Handbook"}
  ]
}
```

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `RERANK_TOP_N` | 6 | Passages the answer may cite |
| `EVIDENCE_MAX_PER_DOCUMENT` | 3 | Slots one document may take while others have relevant passages |
| `CONTEXT_MAX_TOKENS` | 6000 | Evidence budget sent to the model (unchanged) |

## Upload time in the index

New uploads store the version's upload time (`uploaded_at`) on every vector, for
the tie-break. Documents indexed earlier have no upload time; for them the tie
rule simply does not apply, and everything else works as described. A new
version adds it. `python -m app.ops reindex` also adds it, but re-embeds every
document and so spends embedding tokens; it is not needed for this feature.

## Behaviour that did not change

- With one document and no repeated text, the evidence is exactly the
  reranker's top 6, as before.
- Scope rules (tenant, restricted documents, latest version) are unchanged.
- Token use per question is unchanged: the same 6 passages and the same 6,000
  token budget; merging repeats only makes room for different evidence.

## Also in Phase 25

- **Document viewer**: the original PDF or image is shown on the document page
  (Word and Excel offer a download); a download button on every library row.
- **Ask this document**: a chat beside the document, limited to it; citations
  open the cited PDF page or clause.
- **Sensitive-data warnings**: bank account numbers (when labelled), passport
  numbers (after "passport"), UPI IDs, and passwords or API keys are detected in
  addition to Aadhaar, PAN, card, email and phone; sensitive documents get a
  badge in the library, a warning on the document and in its chat, and an alert
  right after upload. Only counts are stored, never the values (see
  [enterprise-security.md](enterprise-security.md)).
- **Sources under every answer**: the documents an answer came from, with
  version, pages and citation numbers.
