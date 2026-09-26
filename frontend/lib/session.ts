"use client";

import { useEffect, useState } from "react";
import { apiRequest, getAccessToken } from "@/lib/api-client";
import { config } from "@/lib/config";

/** The signed-in user and their organization, for the app shell. */
export interface Me {
  name: string;
  role: string;
  organization: string;
  members: number;
}

interface ApiMe {
  full_name: string;
  role: string;
  organization_name: string;
  member_count: number;
}

const DEMO_ME: Me = { name: "Sunil Gupta", role: "Admin", organization: "Acme Legal", members: 12 };

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Admin",
  LEGAL_MANAGER: "Legal manager",
  ANALYST: "Analyst",
  VIEWER: "Viewer",
};

// One /users/me request per signed-in token, shared by every component.
let cache: { token: string; promise: Promise<Me> } | null = null;

export function loadMe(): Promise<Me> {
  if (config.useDemoData) return Promise.resolve(DEMO_ME);
  const token = getAccessToken() ?? "";
  if (!cache || cache.token !== token) {
    const promise = apiRequest<ApiMe>("/users/me").then((me) => ({
      name: me.full_name,
      role: ROLE_LABELS[me.role] ?? me.role,
      organization: me.organization_name,
      members: me.member_count,
    }));
    promise.catch(() => {
      if (cache?.promise === promise) cache = null; // retry on next use
    });
    cache = { token, promise };
  }
  return cache.promise;
}

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(config.useDemoData ? DEMO_ME : null);
  useEffect(() => {
    let live = true;
    loadMe()
      .then((value) => live && setMe(value))
      .catch(() => undefined); // 401 already redirects to /login
    return () => {
      live = false;
    };
  }, []);
  return me;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts.at(-1)![0] : "")).toUpperCase() || "?";
}
