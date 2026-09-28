"use client";

import { useRouter } from "next/navigation";
import { useState, type ComponentType, type InputHTMLAttributes } from "react";
import {
  ArrowRight,
  Building2,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LockKeyhole,
  Mail,
  Quote,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import { ErrorState } from "@/components/ui/states";
import { ApiError, apiRequest, setSession } from "@/lib/api-client";
import { config } from "@/lib/config";
import {
  fieldErrorsFromApi,
  passwordChecks,
  validateFullName,
  validateNewEmail,
  validateNewPassword,
  validateOrganization,
  validateSignInEmail,
  validateSignInPassword,
  PASSWORD_MIN,
} from "@/utils/auth-validation";
import { cn } from "@/utils/cn";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

type Mode = "signin" | "register";
type FieldName = "full_name" | "organization_name" | "email" | "password";

// Order in which invalid fields get focus on submit.
const FIELD_ORDER: FieldName[] = ["full_name", "organization_name", "email", "password"];

const COPY: Record<Mode, { title: string; subtitle: string; action: string }> = {
  signin: {
    title: "Welcome back",
    subtitle: "Your documents are ready. Ask away.",
    action: "Sign in",
  },
  register: {
    title: "Start your workspace",
    subtitle: "Upload. Ask. Get cited answers. You'll be the admin.",
    action: "Create organization",
  },
};

export function LoginForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [organization, setOrganization] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // Field messages appear once a field was left (blur) or the form was
  // submitted, never while someone is still typing their first characters.
  const [touched, setTouched] = useState<Partial<Record<FieldName, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Partial<Record<FieldName, string>>>({});
  const copy = COPY[mode];
  const register = mode === "register";
  const personal = [email, fullName, organization];

  const clientErrors: Partial<Record<FieldName, string | null>> = register
    ? {
        full_name: validateFullName(fullName),
        organization_name: validateOrganization(organization),
        email: validateNewEmail(email),
        password: validateNewPassword(password, personal),
      }
    : { email: validateSignInEmail(email), password: validateSignInPassword(password) };

  function shown(field: FieldName): string | null {
    return serverErrors[field] ?? (touched[field] || submitted ? clientErrors[field] ?? null : null);
  }

  function edit(field: FieldName, set: (v: string) => void) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      set(e.target.value);
      if (serverErrors[field]) setServerErrors(({ [field]: _, ...rest }) => rest);
    };
  }

  function leave(field: FieldName) {
    return () => setTouched((t) => ({ ...t, [field]: true }));
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setSubmitted(false);
    setTouched({});
    setServerErrors({});
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    const firstInvalid = FIELD_ORDER.find((f) => clientErrors[f]);
    if (firstInvalid) {
      document.getElementById(`auth-${firstInvalid}`)?.focus();
      return;
    }
    setLoading(true);
    try {
      if (!config.useDemoData) {
        // Phase 2: tokens should move to httpOnly cookies set by a BFF route
        // so they are never readable by page scripts.
        const tokens = register
          ? await apiRequest<TokenPair>("/auth/register", {
              method: "POST",
              body: {
                email: email.trim(),
                password,
                full_name: fullName.trim(),
                organization_name: organization.trim(),
              },
            })
          : await apiRequest<TokenPair>("/auth/login", { method: "POST", body: { email: email.trim(), password } });
        setSession(tokens.access_token, tokens.refresh_token);
      }
      router.push("/");
    } catch (err) {
      const fields = fieldErrorsFromApi(err) as Partial<Record<FieldName, string>>;
      if (Object.keys(fields).length > 0) {
        setServerErrors(fields);
        document.getElementById(`auth-${FIELD_ORDER.find((f) => fields[f]) ?? "email"}`)?.focus();
      } else {
        setError(err instanceof ApiError ? err : new ApiError("Sign-in failed.", "UNKNOWN", 0, null));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="animate-fade-up">
      <div className="rounded-2xl border border-line bg-surface/90 p-6 shadow-lift backdrop-blur sm:p-8">
        <div className="mb-5">
          <span className="mb-3.5 grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand-ink ring-1 ring-brand/20">
            {mode === "signin" ? <KeyRound className="h-5 w-5" /> : <Building2 className="h-5 w-5" />}
          </span>
          <h1 className="display text-[26px] leading-tight">{copy.title}</h1>
          <p className="mt-1.5 text-[14px] leading-6 text-ink-2">{copy.subtitle}</p>
        </div>

        {!config.useDemoData && (
          <div role="tablist" aria-label="Account" className="mb-5 grid grid-cols-2 gap-1 rounded-xl bg-sunken p-1">
            {(["signin", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => switchMode(m)}
                className={cn(
                  "h-9 rounded-lg text-[13px] font-medium transition",
                  mode === m ? "bg-surface text-ink shadow-card ring-1 ring-line-strong" : "text-ink-3 hover:text-ink",
                )}
              >
                {m === "signin" ? "Sign in" : "Create organization"}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={submit} noValidate className="space-y-4">
          {error && <ErrorState error={error} />}

          {mode === "register" && (
            <>
              <Field
                id="auth-full_name"
                label="Your name"
                icon={UserRound}
                required
                maxLength={200}
                autoComplete="name"
                value={fullName}
                onChange={edit("full_name", setFullName)}
                onBlur={leave("full_name")}
                error={shown("full_name")}
                placeholder="Priya Sharma"
              />
              <Field
                id="auth-organization_name"
                label="Organization"
                icon={Building2}
                required
                maxLength={200}
                autoComplete="organization"
                value={organization}
                onChange={edit("organization_name", setOrganization)}
                onBlur={leave("organization_name")}
                error={shown("organization_name")}
                placeholder="Acme Legal"
              />
            </>
          )}

          <Field
            id="auth-email"
            label="Work email"
            icon={Mail}
            type="email"
            required
            maxLength={254}
            autoComplete="email"
            inputMode="email"
            spellCheck={false}
            value={email}
            onChange={edit("email", setEmail)}
            onBlur={leave("email")}
            error={shown("email")}
            placeholder="you@company.com"
          />

          <div>
            <Field
              id="auth-password"
              label="Password"
              icon={LockKeyhole}
              type={showPassword ? "text" : "password"}
              required
              autoComplete={register ? "new-password" : "current-password"}
              value={password}
              onChange={edit("password", setPassword)}
              onBlur={leave("password")}
              error={shown("password")}
              placeholder={register ? `At least ${PASSWORD_MIN} characters` : "Your password"}
              trailing={
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="rounded-md p-1 text-ink-3 transition hover:text-ink"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              }
            />
            {register ? (
              <PasswordChecklist password={password} personal={personal} />
            ) : (
              <p className="mt-2 text-2xs text-ink-3">Forgot your password? Ask your organization&apos;s admin to reset it.</p>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            className="group inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand text-[14px] font-semibold text-white shadow-sm transition hover:bg-brand/90 disabled:pointer-events-none disabled:opacity-60 dark:text-rail"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                {copy.action}
                <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </form>

        <div className="mt-6 grid grid-cols-3 gap-2 border-t border-line pt-5 text-center text-2xs leading-4 text-ink-3">
          <Trust icon={ShieldCheck} label="Private to your organization" />
          <Trust icon={UsersRound} label="Role-based access" />
          <Trust icon={Quote} label="Every answer cited" />
        </div>
      </div>

      <p className="mt-6 text-center text-2xs text-ink-3">
        AI-assisted document analysis · not legal advice
      </p>
    </div>
  );
}

/** Live password rules; ticks turn green as each one is met. */
export function PasswordChecklist({ password, personal }: { password: string; personal: (string | undefined)[] }) {
  return (
    <ul className="mt-2 space-y-1" aria-label="Password requirements">
      {passwordChecks(password, personal).map((check) => (
        <li key={check.id} className={cn("flex items-center gap-1.5 text-2xs", check.ok ? "text-ok" : "text-ink-3")}>
          <Check className={cn("h-3.5 w-3.5 shrink-0", !check.ok && "opacity-40")} aria-hidden />
          {check.label}
          <span className="sr-only">{check.ok ? "(met)" : "(not met)"}</span>
        </li>
      ))}
      <li className="text-2xs text-ink-3">A short phrase of a few words is easiest to remember.</li>
    </ul>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  icon: ComponentType<{ className?: string }>;
  trailing?: React.ReactNode;
  /** Shown under the field, which is then marked invalid for screen readers. */
  error?: string | null;
}

export function Field({ label, icon: Icon, trailing, className, error, id, ...input }: FieldProps) {
  const messageId = id ? `${id}-error` : undefined;
  return (
    <label className="block" htmlFor={id}>
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      <span
        className={cn(
          "group flex h-11 items-center gap-2.5 rounded-xl border bg-sunken/60 px-3.5 transition focus-within:bg-surface focus-within:ring-4",
          error
            ? "border-danger/60 focus-within:border-danger/70 focus-within:ring-danger/10"
            : "border-line focus-within:border-brand/60 focus-within:ring-brand/10",
        )}
      >
        <Icon className={cn("h-4 w-4 shrink-0 transition", error ? "text-danger" : "text-ink-3 group-focus-within:text-brand")} />
        <input
          {...input}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? messageId : undefined}
          className={cn(
            // The whole field shows focus (ring on the wrapper), not the bare input.
            "h-full w-full bg-transparent text-[14px] text-ink placeholder:text-ink-3 focus:outline-none focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0",
            className,
          )}
        />
        {trailing}
      </span>
      {error && (
        <span id={messageId} role="alert" className="mt-1.5 block text-2xs leading-4 text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

function Trust({ icon: Icon, label }: { icon: ComponentType<{ className?: string }>; label: string }) {
  return (
    <span className="flex flex-col items-center gap-1.5">
      <Icon className="h-4 w-4 text-brand" />
      {label}
    </span>
  );
}
