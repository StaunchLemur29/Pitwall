import { describe, expect, it } from "vitest";
import { DebriefError, makeHandler, parseEmails, type DebriefRow, type Deps } from "../../../cloud/supabase/functions/debrief/handler";

const summary = { car: "c", track: "t", session: { start: 1_700_000_000 } };
const body = { game: "ac", car: "c", track_key: "t", summary };

function setup(over: Partial<Deps> = {}) {
  const saved: DebriefRow[] = [];
  const calls: unknown[] = [];
  const deps: Deps = {
    apiKeySet: true,
    allowedEmails: parseEmails(" Me@Example.com, other@x.nz "),
    userFor: async (t) => (t === "good" ? { id: "u1", email: "me@example.com" } : t === "stranger" ? { id: "u2", email: "s@x.com" } : null),
    write: async (s) => {
      calls.push(s);
      return ["**Good session.**", "claude-opus-5-5"];
    },
    save: async (_t, row) => {
      saved.push(row);
    },
    now: () => 1_700_000_100_000,
    ...over,
  };
  const h = makeHandler(deps);
  const post = (b: unknown, token = "good") =>
    h(new Request("https://x/functions/v1/debrief", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(b) }));
  return { post, saved, calls, h };
}

describe("debrief function", () => {
  it("writes and saves a debrief for an allowed user", async () => {
    const { post, saved, calls } = setup();
    const r = await post(body);
    expect(r.status).toBe(200);
    const row = await r.json();
    expect(row).toMatchObject({ user_id: "u1", game: "ac", car: "c", track_key: "t", body: "**Good session.**", model: "claude-opus-5-5" });
    expect(row.session_start).toBe(new Date(1_700_000_000_000).toISOString());
    expect(saved).toHaveLength(1);
    expect(calls).toEqual([summary]);
  });

  it("refuses people not signed in, and accounts not on the list", async () => {
    const { post, calls } = setup();
    expect((await post(body, "nope")).status).toBe(401);
    const r = await post(body, "stranger");
    expect(r.status).toBe(403);
    expect(calls).toHaveLength(0);
  });

  it("reports whether it's set up", async () => {
    expect(await (await setup().post({ action: "status" })).json()).toEqual({ configured: true, allowed: true });
    expect(await (await setup({ apiKeySet: false }).post({ action: "status" }, "stranger")).json()).toEqual({ configured: false, allowed: false });
  });

  it("says when the key isn't set", async () => {
    const r = await setup({ apiKeySet: false }).post(body);
    expect(r.status).toBe(503);
    expect((await r.json()).error).toMatch(/API key/);
  });

  it("passes Claude's problems on in plain words", async () => {
    const r = await setup({ write: async () => { throw new DebriefError("Your Anthropic account is out of credit.", 402); } }).post(body);
    expect(r.status).toBe(402);
    expect((await r.json()).error).toBe("Your Anthropic account is out of credit.");
  });

  it("rejects malformed requests", async () => {
    const { post } = setup();
    expect((await post({ ...body, summary: { session: {} } })).status).toBe(400);
    expect((await post({ ...body, car: "" })).status).toBe(400);
    expect((await post({ ...body, summary: { session: { start: 1 }, pad: "x".repeat(300_000) } })).status).toBe(413);
  });

  it("answers the browser's CORS check", async () => {
    const r = await setup().h(new Request("https://x", { method: "OPTIONS" }));
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });
});
