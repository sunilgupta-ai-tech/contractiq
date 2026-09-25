"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiError, apiRequest, setAccessToken } from "@/lib/api-client";
import { config } from "@/lib/config";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export function LoginForm() {
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
      if (!config.useDemoData) {
        // Phase 2: tokens should move to httpOnly cookies set by a BFF route
        // so they are never readable by page scripts.
        const tokens = await apiRequest<TokenPair>("/auth/login", { method: "POST", body: { email, password } });
        setAccessToken(tokens.access_token);
      }
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Sign-in failed.", "UNKNOWN", 0, null));
    } finally {
      setLoading(false);
    }
  }

  const field = "mt-1.5 h-10 w-full rounded-lg border border-line bg-surface px-3 text-[14px] text-ink shadow-card placeholder:text-ink-3 focus:border-brand/60 focus:outline-none";

  return (
    <form onSubmit={submit} className="mt-8 space-y-4">
      {error && <ErrorState error={error} />}
      <label className="block text-[13px] font-medium text-ink">
        Work email
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className={field} />
      </label>
      <label className="block text-[13px] font-medium text-ink">
        <span className="flex justify-between">Password <a href="#" className="font-normal text-brand hover:underline">Forgot?</a></span>
        <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
      </label>
      <Button type="submit" className="w-full" disabled={loading}>
        {loading && <Loader2 className="h-4 w-4 animate-spin" />} Sign in
      </Button>
      <p className="pt-2 text-center text-2xs text-ink-3">
        Protected by JWT sessions, role-based access and per-organization data isolation.
      </p>
    </form>
  );
}
