import { afterEach, describe, expect, it, vi } from "vitest";
import { api, setApiHost, UNAUTHORIZED_EVENT, wsUrl } from "./api";

function respond(status, body, headers = {}) {
  // A fresh Response per call: a body can only be read once
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } }));
}

describe("api", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends JSON with the session cookie and query parameters", async () => {
    const fetch = respond(200, { data: [] });
    await api.get("/agents", { status: "running" });
    await api.post("/groups", { name: "red" });
    expect(fetch.mock.calls[0][0]).toBe("/api/agents?status=running");
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "GET", credentials: "include" });
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ name: "red" }) });
  });

  it("uses the server's error message", async () => {
    respond(400, { detail: "Group already exists" });
    await expect(api.createGroup({ name: "red" })).rejects.toThrow("Group already exists");
  });

  it("adds the request ID to server errors so admins can find them in the logs", async () => {
    respond(500, { detail: "Internal server error" }, { "X-Request-ID": "abc123" });
    await expect(api.getAgents()).rejects.toThrow("Internal server error (request ID abc123)");
  });

  it("doesn't repeat a request ID the message already carries", async () => {
    respond(500, { detail: "Failed (request ID abc123)" }, { "X-Request-ID": "abc123" });
    await expect(api.getAgents()).rejects.toThrow(/^Failed \(request ID abc123\)$/);
  });

  it("signals an expired session on 401, except from the sign-in endpoints", async () => {
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);
    respond(401, { detail: "Not signed in" });
    await expect(api.getAgents()).rejects.toThrow("Not signed in");
    expect(listener).toHaveBeenCalledTimes(1);
    await expect(api.login({ username: "a", password: "b" })).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
  });

  it("encodes backup names in download links", () => {
    expect(api.backupDownloadUrl("a b.tar.gz")).toBe("/api/system/backups/a%20b.tar.gz");
  });
});

describe("working on another host", () => {
  afterEach(() => setApiHost(null));

  it("sends the host's API calls through this server's relay", async () => {
    const fetch = respond(200, { data: {} });
    setApiHost(7);
    await api.getAgents({ limit: 5 });
    await api.getMyTokens();
    await api.getHosts();
    await api.getBackups();
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([
      "/api/hosts/7/api/agents?limit=5",
      "/api/users/me/tokens", // accounts, hosts and backups stay with this server
      "/api/hosts",
      "/api/system/backups",
    ]);
    expect(api.reportDownloadUrl("r1", "pdf")).toBe("/api/hosts/7/api/reports/r1/download?format=pdf");
    expect(wsUrl("/ws/metrics")).toMatch(/^ws:\/\/[^/]+\/hosts\/7\/ws\/metrics$/);
    setApiHost(null);
    expect(wsUrl("/ws/metrics")).toMatch(/^ws:\/\/[^/]+\/ws\/metrics$/);
  });
});
