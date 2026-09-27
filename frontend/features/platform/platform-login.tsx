"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Loader2, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";
import { platformService } from "@/services/platform-service";

export function PlatformLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await platformService.login(email, password);
      router.push("/platform");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Sign-in failed.", "UNKNOWN", 0, null));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-rail px-5 py-12">
      <div className="w-full max-w-[400px] animate-fade-up">
        <div className="mb-6 flex items-center justify-between">
          <Logo className="text-rail-ink" />
          <span className="rounded-md border border-[#E8B04B]/40 px-2 py-0.5 text-2xs font-semibold uppercase tracking-[0.12em] text-[#E8B04B]">
            Platform
          </span>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-surface p-7 shadow-lift">
          <div>
            <h1 className="display text-[24px]">Platform console</h1>
            <p className="mt-1 text-[13.5px] text-ink-2">For DocuNexa AI operators. Organization users sign in at the main page.</p>
          </div>
          {error && <ErrorState error={error} />}
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Email</span>
            <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-sunken/60 px-3.5 focus-within:border-brand/60 focus-within:bg-surface">
              <Mail className="h-4 w-4 text-ink-3" />
              <input required type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="h-full w-full bg-transparent text-[14px] text-ink focus:outline-none focus-visible:outline-none focus-visible:ring-0" />
            </span>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Password</span>
            <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-sunken/60 px-3.5 focus-within:border-brand/60 focus-within:bg-surface">
              <LockKeyhole className="h-4 w-4 text-ink-3" />
              <input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-full w-full bg-transparent text-[14px] text-ink focus:outline-none focus-visible:outline-none focus-visible:ring-0" />
            </span>
          </label>
          <button type="submit" disabled={loading} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand text-[14px] font-semibold text-white transition hover:bg-brand/90 disabled:opacity-60 dark:text-rail">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Sign in <ArrowRight className="h-4 w-4" /></>}
          </button>
          <p className="flex items-center gap-1.5 text-2xs text-ink-3">
            <ShieldCheck className="h-3.5 w-3.5 text-brand" /> Every action here is recorded in the platform audit log.
          </p>
        </form>
      </div>
    </div>
  );
}
