import { afterEach, describe, expect, it, vi } from "vitest";
import { isStaleBuildError, reloadOnce } from "@/lib/stale-build";

describe("isStaleBuildError", () => {
  it("recognises the errors an outdated build produces", () => {
    const chunk = Object.assign(new Error("Loading chunk 931 failed."), { name: "ChunkLoadError" });
    expect(isStaleBuildError(chunk)).toBe(true);
    expect(isStaleBuildError(new Error("Loading CSS chunk app-layout failed"))).toBe(true);
    expect(isStaleBuildError(new TypeError("Failed to fetch dynamically imported module: /_next/x.js"))).toBe(true);
  });

  it("leaves real bugs alone", () => {
    expect(isStaleBuildError(new TypeError("Cannot read properties of undefined (reading 'map')"))).toBe(false);
    expect(isStaleBuildError("Loading chunk 1 failed")).toBe(false); // not an Error
  });
});

describe("reloadOnce", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reloads once, then refuses within the loop guard", () => {
    const store = new Map<string, string>();
    const reload = vi.fn();
    vi.stubGlobal("window", {
      location: { reload },
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    });
    expect(reloadOnce()).toBe(true);
    expect(reloadOnce()).toBe(false); // a broken page can't cause a reload loop
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("newBuildDeployed", () => {
  afterEach(() => vi.unstubAllGlobals());

  const server = (body: unknown, ok = true) =>
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok, json: async () => body })));

  it("compares the server's build with this tab's", async () => {
    const { newBuildDeployed } = await import("@/lib/stale-build");
    server({ buildId: "b2" });
    expect(await newBuildDeployed("b1")).toBe(true);
    expect(await newBuildDeployed("b2")).toBe(false);
  });

  it("never claims staleness it can't confirm", async () => {
    const { newBuildDeployed } = await import("@/lib/stale-build");
    server({}, false);
    expect(await newBuildDeployed("b1")).toBe(false); // server error
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    expect(await newBuildDeployed("b1")).toBe(false);
    expect(await newBuildDeployed("")).toBe(false); // unknown own build
  });
});
