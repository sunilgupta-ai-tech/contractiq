import type { Metadata } from "next";
import { LoginForm } from "@/features/auth/login-form";
import { Logo } from "@/components/ui/logo";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-rail p-12 text-rail-ink lg:flex lg:flex-col">
        <div className="pointer-events-none absolute inset-0 opacity-[0.06]" style={{ backgroundImage: "repeating-linear-gradient(0deg, transparent 0 31px, #fff 31px 32px)" }} aria-hidden />
        <div className="pointer-events-none absolute -bottom-24 -right-10 font-serif text-[420px] leading-none text-white/[0.035]" aria-hidden>§</div>
        <Logo className="relative" />
        <div className="relative mt-auto max-w-lg">
          <p className="font-serif text-[40px] leading-[1.12]">Read every contract. Cite every answer.</p>
          <p className="mt-5 text-[15px] leading-7 text-rail-mute">
            ContractIQ parses digital and scanned agreements, understands their clause structure, and answers questions with the exact page, section and version behind each claim.
          </p>
          <ul className="mt-8 grid grid-cols-2 gap-3 text-[13px] text-rail-mute">
            {["Tenant-isolated retrieval", "Clause-aware chunking", "Version & amendment diffs", "Evidence-validated answers"].map((f) => (
              <li key={f} className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-brand" /> {f}</li>
            ))}
          </ul>
        </div>
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
