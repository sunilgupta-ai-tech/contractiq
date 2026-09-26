import type { Metadata } from "next";
import { LoginForm } from "@/features/auth/login-form";
import { FileSearch, GitCompareArrows, Lock, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/ui/logo";

const FEATURES = [
  { icon: FileSearch, label: "Understands clauses" },
  { icon: ShieldCheck, label: "Checked against the source" },
  { icon: GitCompareArrows, label: "Compares versions" },
  { icon: Lock, label: "Private to your team" },
];

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-rail px-12 py-10 text-rail-ink lg:flex lg:flex-col">
        <div className="pointer-events-none absolute inset-0 opacity-[0.06]" style={{ backgroundImage: "repeating-linear-gradient(0deg, transparent 0 31px, #fff 31px 32px)" }} aria-hidden />
        <div className="pointer-events-none absolute -bottom-24 -right-10 font-serif text-[420px] leading-none text-white/[0.035]" aria-hidden>§</div>
        <Logo className="relative" />

        <div className="relative my-auto max-w-xl py-8">
          <p className="text-balance font-serif text-[36px] leading-[1.12] xl:text-[40px]">
            Read every contract. <span className="text-brand">Cite every answer.</span>
          </p>
          <p className="mt-4 max-w-lg text-[15px] leading-7 text-rail-mute">
            Upload digital or scanned agreements and ask questions in plain language. Every answer points to the exact page, clause and version it came from.
          </p>

          {/* Illustrative example of an answer; not live data. */}
          <figure className="mt-7 max-w-lg rounded-2xl border border-white/10 bg-white/[0.04] p-5 shadow-lift backdrop-blur" aria-label="Example answer">
            <p className="ml-auto w-fit rounded-2xl rounded-br-md bg-white/10 px-3.5 py-2 text-[13.5px] text-rail-ink">
              What is the termination notice period?
            </p>
            <p className="mt-4 text-[14px] leading-6 text-rail-ink/90">
              Either party may terminate on <strong className="font-semibold text-rail-ink">60 days&apos;</strong> written notice
              <span className="mx-1 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded bg-brand px-1 align-middle font-mono text-[10.5px] font-semibold text-rail">1</span>.
            </p>
            <figcaption className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/10 pt-3 font-mono text-2xs text-rail-mute">
              <span className="rounded bg-white/5 px-1.5 py-0.5">Master Services Agreement</span>
              <span>§8.3 · p.12 · v2</span>
              <span className="ml-auto inline-flex items-center gap-1 text-brand">
                <ShieldCheck className="h-3.5 w-3.5" /> 100% grounded
              </span>
            </figcaption>
          </figure>

          <ul className="mt-7 grid max-w-lg grid-cols-2 gap-x-6 gap-y-3 text-[13px] text-rail-mute">
            {FEATURES.map(({ icon: Icon, label }) => (
              <li key={label} className="flex items-center gap-2.5">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand/15 text-brand">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                {label}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-2xs text-rail-mute/70">© {new Date().getFullYear()} ContractIQ</p>
      </section>
      <section className="relative flex items-center justify-center overflow-hidden px-5 py-12 sm:px-8">
        {/* Soft brand glow behind the card; purely decorative. */}
        <div
          className="pointer-events-none absolute left-1/2 top-1/3 h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand/10 blur-3xl"
          aria-hidden
        />
        <div className="relative w-full max-w-[420px]">
          <Logo className="mb-8 lg:hidden" />
          <LoginForm />
        </div>
      </section>
    </div>
  );
}
