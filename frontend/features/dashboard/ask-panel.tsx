"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowUp, Sparkles } from "lucide-react";
import { suggestedQuestions } from "@/lib/demo/fixtures";

export function AskPanel() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const go = (question: string) => router.push(`/assistant?q=${encodeURIComponent(question)}`);

  return (
    <section className="relative overflow-hidden rounded-2xl bg-rail p-6 text-rail-ink shadow-lift sm:p-7">
      {/* Decorative ruled lines — a nod to legal paper. */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{ backgroundImage: "repeating-linear-gradient(0deg, transparent 0 27px, #fff 27px 28px)" }}
        aria-hidden
      />
      <div className="pointer-events-none absolute -right-10 -top-16 font-serif text-[240px] leading-none text-white/[0.04]" aria-hidden>
        §
      </div>
      <div className="relative">
        <p className="mb-2 inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.12em] text-brand">
          <Sparkles className="h-3.5 w-3.5" /> Agentic contract Q&amp;A
        </p>
        <h2 className="max-w-xl font-serif text-[24px] leading-snug sm:text-[27px]">
          Ask across every contract. Get answers with the clause, page and version.
        </h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim()) go(q.trim());
          }}
          className="mt-5 flex items-center gap-2 rounded-xl bg-white/[0.06] p-1.5 ring-1 ring-white/10 focus-within:ring-brand/60"
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Which contracts have no explicit liability cap?"
            className="h-10 min-w-0 flex-1 bg-transparent px-3 text-[14px] text-rail-ink placeholder:text-rail-mute focus:outline-none"
          />
          <button type="submit" className="grid h-10 w-10 place-items-center rounded-lg bg-brand text-white transition hover:bg-brand/90" aria-label="Ask">
            <ArrowUp className="h-4 w-4" />
          </button>
        </form>
        <div className="mt-4 flex flex-wrap gap-2">
          {suggestedQuestions.slice(1, 4).map((s) => (
            <button key={s} onClick={() => go(s)} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-2xs text-rail-mute transition hover:border-white/25 hover:text-rail-ink">
              {s}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
