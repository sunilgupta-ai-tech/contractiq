"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Loader2, LockKeyhole, UserRound } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError, setSession } from "@/lib/api-client";
import { invitationService } from "@/services/team-service";
import { fieldErrorsFromApi, PASSWORD_MIN, validateFullName, validateNewPassword } from "@/utils/auth-validation";
import { Field, PasswordChecklist } from "./login-form";

type FieldName = "full_name" | "password";

/** Phase 22: join an organization from an invitation link. */
export function AcceptInvitation({ token }: { token: string }) {
  const router = useRouter();
  const invite = useAsync(() => invitationService.preview(token), [token]);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [touched, setTouched] = useState<Partial<Record<FieldName, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Partial<Record<FieldName, string>>>({});
  const personal = [invite.data?.email, name, invite.data?.organizationName];
  const clientErrors: Record<FieldName, string | null> = {
    full_name: validateFullName(name),
    password: validateNewPassword(password, personal),
  };

  function shown(field: FieldName): string | null {
    return serverErrors[field] ?? (touched[field] || submitted ? clientErrors[field] : null);
  }

  function edit(field: FieldName, set: (v: string) => void) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      set(e.target.value);
      if (serverErrors[field]) setServerErrors(({ [field]: _, ...rest }) => rest);
    };
  }

  async function accept(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    const firstInvalid = (["full_name", "password"] as const).find((f) => clientErrors[f]);
    if (firstInvalid) {
      document.getElementById(`join-${firstInvalid}`)?.focus();
      return;
    }
    setSaving(true);
    try {
      const tokens = await invitationService.accept(token, name.trim(), password);
      setSession(tokens.access_token, tokens.refresh_token);
      router.push("/");
    } catch (err) {
      const fields = fieldErrorsFromApi(err) as Partial<Record<FieldName, string>>;
      if (Object.keys(fields).length > 0) setServerErrors(fields);
      else setError(err instanceof ApiError ? err : new ApiError("Could not join.", "UNKNOWN", 0, null));
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
            <form onSubmit={accept} noValidate className="space-y-4">
              <div>
                <h1 className="display text-[24px] leading-tight">Join {invite.data.organizationName}</h1>
                <p className="mt-1 text-[13.5px] text-ink-2">
                  You were invited as <strong>{invite.data.roleName}</strong> with {invite.data.email}.
                </p>
              </div>
              {error && <ErrorState error={error} />}
              <Field
                id="join-full_name"
                label="Your name"
                icon={UserRound}
                required
                maxLength={200}
                autoComplete="name"
                value={name}
                onChange={edit("full_name", setName)}
                onBlur={() => setTouched((t) => ({ ...t, full_name: true }))}
                error={shown("full_name")}
              />
              <div>
                <Field
                  id="join-password"
                  label="Choose a password"
                  icon={LockKeyhole}
                  type="password"
                  required
                  autoComplete="new-password"
                  value={password}
                  onChange={edit("password", setPassword)}
                  onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                  error={shown("password")}
                  placeholder={`At least ${PASSWORD_MIN} characters`}
                />
                <PasswordChecklist password={password} personal={personal} />
              </div>
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
