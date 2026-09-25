// Public, browser-safe configuration only. Secrets (GEMINI_API_KEY, JWT
// secrets, DB URLs) exist exclusively on the backend and must never be
// prefixed NEXT_PUBLIC_.
export const config = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  apiPrefix: "/api/v1",
  useDemoData: (process.env.NEXT_PUBLIC_USE_DEMO_DATA ?? "true") === "true",
  maxUploadMb: 50,
} as const;
