const PERSONAL_DATA: Record<string, [string, string]> = {
  aadhaar: ["Aadhaar number", "Aadhaar numbers"],
  pan: ["PAN", "PANs"],
  card: ["card number", "card numbers"],
  email: ["email address", "email addresses"],
  phone: ["phone number", "phone numbers"],
  bank_account: ["bank account number", "bank account numbers"],
  passport: ["passport number", "passport numbers"],
  upi: ["UPI ID", "UPI IDs"],
  secret: ["password or API key", "passwords or API keys"],
};

/** Kinds that identify a person or open an account; contact details are milder. */
const SENSITIVE = new Set(["aadhaar", "pan", "card", "bank_account", "passport", "upi", "secret"]);

/** Phase 24: {aadhaar: 2, email: 1} → "2 Aadhaar numbers, 1 email address". */
export function personalDataText(found: Record<string, number>): string {
  return Object.entries(found)
    .map(([kind, n]) => {
      const [one, many] = PERSONAL_DATA[kind] ?? [kind, kind];
      return `${n} ${n === 1 ? one : many}`;
    })
    .join(", ");
}

/** "sensitive" (IDs, financial details, credentials), "contact" (only emails and
 *  phone numbers) or null (nothing found). Sensitive kinds are listed first. */
export function personalDataLevel(found: Record<string, number>): "sensitive" | "contact" | null {
  const kinds = Object.keys(found).filter((k) => (found[k] ?? 0) > 0);
  if (kinds.length === 0) return null;
  return kinds.some((k) => SENSITIVE.has(k)) ? "sensitive" : "contact";
}

/** The sensitive kinds only, e.g. for a short warning ("2 Aadhaar numbers, 1 PAN"). */
export function sensitiveText(found: Record<string, number>): string {
  return personalDataText(Object.fromEntries(Object.entries(found).filter(([k]) => SENSITIVE.has(k))));
}
