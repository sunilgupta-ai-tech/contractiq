"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Loader2, LockKeyhole, UserRound } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError, setSession } from "@/lib/api-client";
import { invitationService } from "@/services/team-service";

const MIN_PASSWORD = 12;

/** Phase 22: join an organization from an invitation link. */
export function AcceptInvitation({ token }: { token: string }) {
  const router = useRouter();
  const invite = useAsync(() => invitationService.preview(token), [token]);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function accept(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const tokens = await invitationService.accept(token, name, password);
      setSession(tokens.access_token, tokens.refresh_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Could not join.", "UNKNOWN", 0, null));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-5 py-12">
      <div className="w-full max-w-[420px] animate-fade-up">
        <Logo className="mb-6" />
        <div className="rounded-2xl border border-line bg-surface p-7 shadow-lift">
          {invite.error ? (
            <ErrorState error={invite.error} />
          ) : !invite.data ? (
            <Skeleton className="h-48" />
          ) : (
            <form onSubmit={accept} className="space-y-4">
              <div>
                <h1 className="display text-[24px] leading-tight">Join {invite.data.organizationName}</h1>
                <p className="mt-1 text-[13.5px] text-ink-2">
                  You were invited as <strong>{invite.data.roleName}</strong> with {invite.data.email}.
                </p>
              </div>
              {error && <ErrorState error={error} />}
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Your name</span>
                <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-sunken/60 px-3.5 focus-within:border-brand/60">
                  <UserRound className="h-4 w-4 text-ink-3" />
                  <input required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className="h-full w-full bg-transparent text-[14px] focus:outline-none focus-visible:outline-none focus-visible:ring-0" />
                </span>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Choose a password</span>
                <span className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-sunken/60 px-3.5 focus-within:border-brand/60">
                  <LockKeyhole className="h-4 w-4 text-ink-3" />
                  <input required minLength={MIN_PASSWORD} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={`At least ${MIN_PASSWORD} characters`} className="h-full w-full bg-transparent text-[14px] focus:outline-none focus-visible:outline-none focus-visible:ring-0" />
                </span>
              </label>
              <button type="submit" disabled={saving} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand text-[14px] font-semibold text-white hover:bg-brand/90 disabled:opacity-60 dark:text-rail">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Join and sign in <ArrowRight className="h-4 w-4" /></>}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
