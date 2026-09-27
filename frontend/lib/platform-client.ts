/**
 * API client for the platform console (Phase 18).
 *
 * Deliberately separate from lib/api-client.ts: its own token storage keys,
 * refresh endpoint and sign-in page, so an organization session and a
 * platform session never mix — not even in the same browser tab.
 */

import { ApiError, parseEnvelope } from "@/lib/api-client";
import { config } from "@/lib/config";

const TOKEN_KEY = "dnx.platform.access_token";
const REFRESH_KEY = "dnx.platform.refresh_token";
export const PLATFORM_LOGIN = "/platform/login";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function hasPlatformSession(): boolean {
  return Boolean(storage()?.getItem(TOKEN_KEY));
}

export function setPlatformSession(access: string, refresh: string): void {
  storage()?.setItem(TOKEN_KEY, access);
  storage()?.setItem(REFRESH_KEY, refresh);
}

function clear(): void {
  storage()?.removeItem(TOKEN_KEY);
  storage()?.removeItem(REFRESH_KEY);
}

const url = (path: string) => `${config.apiBaseUrl}${config.apiPrefix}/platform${path}`;

let renewal: Promise<boolean> | null = null;

async function renew(): Promise<boolean> {
  const refresh = storage()?.getItem(REFRESH_KEY);
  if (!refresh) return false;
  try {
    const response = await fetch(url("/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!response.ok) return false;
    const data = parseEnvelope<{ access_token: string; refresh_token: string }>(
      response.status,
      await response.json(),
    );
    setPlatformSession(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

function renewOnce(): Promise<boolean> {
  if (!renewal) renewal = renew().finally(() => (renewal = null));
  return renewal;
}

export async function platformRequest<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
  mayRenew = true,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url(path), {
      method: options.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(storage()?.getItem(TOKEN_KEY) ? { Authorization: `Bearer ${storage()?.getItem(TOKEN_KEY)}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError("Cannot reach the DocuNexa AI server.", "NETWORK_ERROR", 0, null);
  }
  if (response.status === 401 && !path.startsWith("/auth/")) {
    if (mayRenew && (await renewOnce())) return platformRequest<T>(path, options, false);
    clear();
    if (typeof window !== "undefined" && window.location.pathname !== PLATFORM_LOGIN) {
      window.location.assign(PLATFORM_LOGIN);
    }
  }
  const payload = await response.json().catch(() => null);
  return parseEnvelope<T>(response.status, payload);
}

export async function platformSignOut(): Promise<void> {
  const refresh = storage()?.getItem(REFRESH_KEY);
  if (refresh) {
    await fetch(url("/auth/logout"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => undefined);
  }
  clear();
  window.location.assign(PLATFORM_LOGIN);
}
