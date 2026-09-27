import { config } from "@/lib/config";

/**
 * Typed fetch wrapper for the DocuNexa AI API.
 *
 * The backend always responds with an envelope:
 *   { success: true,  data, request_id }
 *   { success: false, error: { code, message, details? }, request_id }
 * This client unwraps `data` or throws an `ApiError` carrying the code and
 * request ID, so UI error states can show a reference users can quote to support.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
    public readonly requestId: string | null,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface Envelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string; details?: Record<string, unknown> };
  request_id?: string | null;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  timeoutMs?: number;
  /** Return `data` even when success=false (e.g. readiness 503 carries a report). */
  acceptErrorData?: boolean;
}

// The access token lives in sessionStorage: it survives a page reload but
// not closing the tab, and is never sent to other origins. (A BFF with
// httpOnly cookies remains the planned hardening; see docs/security.md.)
const TOKEN_KEY = "ciq.access_token";
const REFRESH_KEY = "ciq.refresh_token";
let accessToken: string | null = null;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null; // storage disabled (privacy mode)
  }
}

export const setAccessToken = (token: string | null) => {
  accessToken = token;
  const store = storage();
  if (!store) return;
  if (token) store.setItem(TOKEN_KEY, token);
  else store.removeItem(TOKEN_KEY);
};

export const getAccessToken = (): string | null => {
  if (accessToken === null) accessToken = storage()?.getItem(TOKEN_KEY) ?? null;
  return accessToken;
};

export const hasSession = (): boolean => getAccessToken() !== null;

/** Store both tokens after sign-in / sign-up. The refresh token lets the
 *  session be renewed silently when the (short-lived) access token expires. */
export function setSession(access: string, refresh: string): void {
  setAccessToken(access);
  try {
    storage()?.setItem(REFRESH_KEY, refresh);
  } catch {
    // storage unavailable: the session simply can't be renewed
  }
}

function clearSession(): void {
  setAccessToken(null);
  try {
    storage()?.removeItem(REFRESH_KEY);
  } catch {
    // nothing to clear
  }
}

// Refresh tokens are single-use (Phase 2), so concurrent 401s must share one
// renewal: the second caller waits for the first instead of spending an
// already-used token and failing.
let renewal: Promise<boolean> | null = null;

async function renewSession(): Promise<boolean> {
  const refresh = storage()?.getItem(REFRESH_KEY);
  if (!refresh) return false;
  try {
    const response = await fetch(`${config.apiBaseUrl}${config.apiPrefix}/auth/refresh`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!response.ok) return false;
    const payload = (await response.json()) as Envelope<{ access_token: string; refresh_token: string }>;
    if (!payload.data) return false;
    setSession(payload.data.access_token, payload.data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export function refreshSession(): Promise<boolean> {
  if (!renewal) renewal = renewSession().finally(() => (renewal = null));
  return renewal;
}

/** Sign out: revoke the refresh token on the server (best effort; the user
 *  is signed out locally either way), forget both tokens, go to /login. */
export async function signOut(): Promise<void> {
  const refresh = storage()?.getItem(REFRESH_KEY);
  if (refresh && !config.useDemoData) {
    try {
      await fetch(`${config.apiBaseUrl}${config.apiPrefix}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch {
      // offline: the token still expires on its own
    }
  }
  clearSession();
  if (typeof window !== "undefined") window.location.assign("/login");
}

/** The session is over (renewal failed): sign in again. */
function onUnauthorized(path: string): void {
  if (path.startsWith("/auth/") || typeof window === "undefined") return;
  clearSession();
  if (window.location.pathname !== "/login") window.location.assign("/login");
}

export function parseEnvelope<T>(status: number, payload: unknown, acceptErrorData = false): T {
  // 204 No Content (e.g. DELETE) has no envelope by design.
  if (status === 204) return undefined as T;
  const env = payload as Envelope<T> | null;
  if (!env || typeof env !== "object" || !("success" in env)) {
    throw new ApiError("Unexpected response from server.", "BAD_RESPONSE", status, null);
  }
  if (env.success || (acceptErrorData && env.data !== undefined)) {
    return env.data as T;
  }
  const err = env.error ?? { code: "UNKNOWN", message: "Request failed." };
  throw new ApiError(err.message, err.code, status, env.request_id ?? null, err.details);
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return send<T>(path, options, true);
}

async function send<T>(path: string, options: RequestOptions, mayRenew: boolean): Promise<T> {
  const { body, timeoutMs = 15_000, acceptErrorData, headers, ...init } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  try {
    const response = await fetch(`${config.apiBaseUrl}${config.apiPrefix}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    if (response.status === 401 && !config.useDemoData && !path.startsWith("/auth/")) {
      // Expired access token: renew silently and send the same request again,
      // so the user's question (or upload) isn't lost.
      if (mayRenew && (await refreshSession())) {
        clearTimeout(timer);
        return send<T>(path, options, false);
      }
      onUnauthorized(path);
    }
    return parseEnvelope<T>(response.status, payload, acceptErrorData);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted ? "The server took too long to respond." : "Cannot reach the DocuNexa AI server.",
      aborted ? "TIMEOUT" : "NETWORK_ERROR",
      0,
      null,
    );
  } finally {
    clearTimeout(timer);
  }
}
