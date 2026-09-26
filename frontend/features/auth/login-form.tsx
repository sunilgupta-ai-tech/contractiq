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
import { cn } from "@/utils/cn";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

type Mode = "signin" | "register";

const MIN_PASSWORD = 12; // backend policy (app/schemas/auth.py)

const COPY: Record<Mode, { title: string; subtitle: string; action: string }> = {
  signin: {
    title: "Welcome back",
    subtitle: "Sign in to your organization's contract workspace.",
    action: "Sign in",
  },
  register: {
    title: "Create your organization",
    subtitle: "Start a private workspace. You'll be its administrator.",
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
  const copy = COPY[mode];
  const passwordLongEnough = password.length >= MIN_PASSWORD;

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (!config.useDemoData) {
        // Phase 2: tokens should move to httpOnly cookies set by a BFF route
        // so they are never readable by page scripts.
        const tokens =
          mode === "signin"
            ? await apiRequest<TokenPair>("/auth/login", { method: "POST", body: { email, password } })
            : await apiRequest<TokenPair>("/auth/register", {
                method: "POST",
                body: { email, password, full_name: fullName, organization_name: organization },
              });
        setSession(tokens.access_token, tokens.refresh_token);
      }
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Sign-in failed.", "UNKNOWN", 0, null));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="animate-fade-up">
      <div className="rounded-2xl border border-line bg-surface/90 p-7 shadow-lift backdrop-blur sm:p-8">
        <div className="mb-6">
          <span className="mb-4 grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand-ink ring-1 ring-brand/20">
            {mode === "signin" ? <KeyRound className="h-5 w-5" /> : <Building2 className="h-5 w-5" />}
          </span>
          <h1 className="display text-[26px] leading-tight">{copy.title}</h1>
          <p className="mt-1.5 text-[14px] leading-6 text-ink-2">{copy.subtitle}</p>
        </div>

        {!config.useDemoData && (
          <div role="tablist" aria-label="Account" className="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-sunken p-1">
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

        <form onSubmit={submit} className="space-y-4">
          {error && <ErrorState error={error} />}

          {mode === "register" && (
            <>
              <Field
                label="Your name"
                icon={UserRound}
                required
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Priya Sharma"
              />
              <Field
                label="Organization"
                icon={Building2}
                required
                minLength={2}
                autoComplete="organization"
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                placeholder="Acme Legal"
              />
            </>
          )}

          <Field
            label="Work email"
            icon={Mail}
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />

          <div>
            <Field
              label="Password"
              icon={LockKeyhole}
              type={showPassword ? "text" : "password"}
              required
              minLength={mode === "register" ? MIN_PASSWORD : undefined}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? `At least ${MIN_PASSWORD} characters` : "Your password"}
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
            {mode === "register" ? (
              <p className={cn("mt-2 flex items-center gap-1.5 text-2xs", passwordLongEnough ? "text-ok" : "text-ink-3")}>
                <Check className={cn("h-3.5 w-3.5", !passwordLongEnough && "opacity-40")} />
                {MIN_PASSWORD}+ characters · a passphrase is easiest to remember
              </p>
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
        AI-assisted contract analysis · not legal advice
      </p>
    </div>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  icon: ComponentType<{ className?: string }>;
  trailing?: React.ReactNode;
}

function Field({ label, icon: Icon, trailing, className, ...input }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      <span className="group flex h-11 items-center gap-2.5 rounded-xl border border-line bg-sunken/60 px-3.5 transition focus-within:border-brand/60 focus-within:bg-surface focus-within:ring-4 focus-within:ring-brand/10">
        <Icon className="h-4 w-4 shrink-0 text-ink-3 transition group-focus-within:text-brand" />
        <input
          {...input}
          className={cn(
            // The whole field shows focus (ring on the wrapper), not the bare input.
            "h-full w-full bg-transparent text-[14px] text-ink placeholder:text-ink-3 focus:outline-none focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0",
            className,
          )}
        />
        {trailing}
      </span>
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
