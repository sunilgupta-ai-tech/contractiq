import { config } from "@/lib/config";

/**
 * Typed fetch wrapper for the ContractIQ API.
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

let accessToken: string | null = null;
export const setAccessToken = (token: string | null) => {
  accessToken = token;
};

export function parseEnvelope<T>(status: number, payload: unknown, acceptErrorData = false): T {
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
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    return parseEnvelope<T>(response.status, payload, acceptErrorData);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted ? "The server took too long to respond." : "Cannot reach the ContractIQ API.",
      aborted ? "TIMEOUT" : "NETWORK_ERROR",
      0,
      null,
    );
  } finally {
    clearTimeout(timer);
  }
}
