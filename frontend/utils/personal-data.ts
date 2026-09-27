const PERSONAL_DATA: Record<string, [string, string]> = {
  aadhaar: ["Aadhaar number", "Aadhaar numbers"],
  pan: ["PAN", "PANs"],
  card: ["card number", "card numbers"],
  email: ["email address", "email addresses"],
  phone: ["phone number", "phone numbers"],
};

/** Phase 24: {aadhaar: 2, email: 1} → "2 Aadhaar numbers, 1 email address". */
export function personalDataText(found: Record<string, number>): string {
  return Object.entries(found)
    .map(([kind, n]) => {
      const [one, many] = PERSONAL_DATA[kind] ?? [kind, kind];
      return `${n} ${n === 1 ? one : many}`;
    })
    .join(", ");
}
