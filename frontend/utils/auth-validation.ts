/**
 * Sign-in / sign-up validation shown while the user types. It mirrors the
 * API's rules (backend/app/core/credentials.py), which stay the authority:
 * anything the browser misses is still refused there, and those messages
 * are mapped back onto the fields by `fieldErrorsFromApi`.
 */

import { ApiError } from "@/lib/api-client";

export const PASSWORD_MIN = 12;
export const PASSWORD_MAX_BYTES = 72;

const COMMON = new Set(
  `password passw0rd passwd pass word admin administrator root user login welcome
  letmein iloveyou qwerty qwertyuiop asdfgh asdfghjkl zxcvbnm abc abcdef abcdefgh
  monkey dragon master shadow sunshine princess football baseball superman batman
  trustno starwars whatever freedom secret changeme default guest test testing
  india bharat hello hellohello computer internet company contract contracts
  docunexa contractiq summer winter spring autumn january december`.split(/\s+/),
);
const SEQUENCES = ["abcdefghijklmnopqrstuvwxyz", "01234567890", "qwertyuiopasdfghjklzxcvbnm", "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik9ol0p"];

const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const DOMAIN_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;
const TLD = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/;
const LOOSE_EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x1f\x7f]/;
const MARKUP = /[<>]|https?:\/\/|www\./i;

const bytes = (s: string) => new TextEncoder().encode(s).length;
// Letters and digits of any script, as Python's [\W_] does in credentials.py.
const compact = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
const squash = (s: string) => s.normalize("NFC").split(/\s+/).filter(Boolean).join(" ");

/** Sign-in: only the basic shape (older accounts must still sign in). */
export function validateSignInEmail(value: string): string | null {
  const v = value.trim();
  if (!v) return "Enter your email address.";
  return LOOSE_EMAIL.test(v) ? null : "Enter a valid email address.";
}

export function validateNewEmail(value: string): string | null {
  const v = value.trim().toLowerCase();
  if (!v) return "Enter your email address.";
  const generic = "Enter a valid email address, like name@company.com.";
  if (v.length > 254 || v.split("@").length !== 2) return generic;
  const [local = "", domain = ""] = v.split("@");
  if (!local || local.length > 64 || !EMAIL_LOCAL.test(local)) return generic;
  const labels = domain.split(".");
  if (labels.length < 2 || !labels.every((l) => DOMAIN_LABEL.test(l)) || !TLD.test(labels.at(-1) ?? "")) {
    return "The part after @ isn't a valid domain, like company.com.";
  }
  return null;
}

function displayText(value: string, what: string, min: number): string | null {
  const v = squash(value);
  if (v.length < min) return min <= 1 ? `Enter ${what}.` : `${capitalize(what)} must be at least ${min} characters.`;
  if (v.length > 200) return `${capitalize(what)} must be at most 200 characters.`;
  if (CONTROL.test(v) || MARKUP.test(v)) return `${capitalize(what)} can't contain links or the characters < and >.`;
  return null;
}

export function validateFullName(value: string): string | null {
  return displayText(value, "your name", 1) ?? (/\p{L}/u.test(value) ? null : "Your name must contain letters.");
}

export function validateOrganization(value: string): string | null {
  return (
    displayText(value, "the organization name", 2) ??
    (/[\p{L}\p{N}]/u.test(value) ? null : "The organization name must contain letters or numbers.")
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export interface PasswordCheck {
  id: "length" | "guessable" | "personal";
  label: string;
  ok: boolean;
  /** Shown under the field when this check fails. */
  message: string;
}

function personalParts(item: string): string[] {
  const text = (item.includes("@") ? item.split("@")[0] : item) ?? "";
  const parts = new Set([compact(text), ...text.split(/[\s._+-]+/).map(compact)]);
  return [...parts].filter((p) => p.length >= 4);
}

/** The password rules, each with its live state (for the checklist). */
export function passwordChecks(password: string, personal: (string | undefined)[] = []): PasswordCheck[] {
  const c = compact(password);
  const stem = c.replace(/\d+$/, "");
  let lengthMessage = "";
  if (password.length < PASSWORD_MIN) lengthMessage = `Password must be at least ${PASSWORD_MIN} characters.`;
  else if (bytes(password) > PASSWORD_MAX_BYTES) lengthMessage = `Password must be at most ${PASSWORD_MAX_BYTES} bytes.`;

  let guessMessage = "";
  if (!password.trim() || CONTROL.test(password)) guessMessage = "Password can't be blank or contain control characters.";
  else if (new Set(password.toLowerCase()).size < 5) guessMessage = "Password repeats too few characters. Use a longer phrase.";
  else if (/^\d+$/.test(c)) guessMessage = "Password can't be only numbers. Use words, e.g. a short phrase.";
  else if (
    COMMON.has(c) ||
    COMMON.has(stem) ||
    (c.length >= 6 && SEQUENCES.some((s) => s.includes(c) || [...s].reverse().join("").includes(c)))
  ) {
    guessMessage = "This password is too common. Choose something less predictable.";
  }

  const leaks = personal.filter(Boolean).some((item) => personalParts(item!).some((p) => c.includes(p)));
  return [
    { id: "length", label: `${PASSWORD_MIN}+ characters`, ok: !lengthMessage, message: lengthMessage },
    { id: "guessable", label: "Not a common word, pattern or only numbers", ok: password.length > 0 && !guessMessage, message: guessMessage },
    {
      id: "personal",
      label: "Doesn't include your name, email or organization",
      ok: password.length > 0 && !leaks,
      message: leaks ? "Password can't contain your email, name or organization name." : "",
    },
  ];
}

export function validateNewPassword(password: string, personal: (string | undefined)[] = []): string | null {
  if (!password) return "Choose a password.";
  return passwordChecks(password, personal).find((check) => !check.ok)?.message || null;
}

export function validateSignInPassword(password: string): string | null {
  return password ? null : "Enter your password.";
}

/** API errors → messages per form field (422 field details, 409 email taken). */
export function fieldErrorsFromApi(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return {};
  if (err.code === "CONFLICT" && /email/i.test(err.message)) return { email: err.message };
  const fields = (err.details?.fields ?? []) as { loc: (string | number)[]; msg: string }[];
  const out: Record<string, string> = {};
  for (const { loc, msg } of fields) {
    const field = String(loc[loc.length - 1]);
    out[field] ??= msg;
  }
  return out;
}
