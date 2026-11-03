/**
 * The hub's "Write debrief" request, without the Supabase / Anthropic wiring
 * (index.ts plugs that in), so it can be tested anywhere.
 *
 * POST {action: "status"}                       -> {configured, allowed}
 * POST {game, car, track_key, summary}          -> the saved debrief
 *
 * Only signed-in users listed in PITWALL_ALLOWED_EMAILS can use it: the API key
 * is yours, so nobody else who signs up to your Supabase project can spend it.
 */

export class DebriefError extends Error {
  constructor(message: string, readonly status = 502) {
    super(message);
  }
}

export interface User {
  id: string;
  email: string | null;
}

export interface DebriefRow {
  user_id: string;
  game: string;
  car: string;
  track_key: string;
  session_start: string; // ISO time
  body: string;
  model: string;
  created_at: string;
}

export interface Deps {
  apiKeySet: boolean;
  allowedEmails: string[];
  /** The signed-in user for this access token, or null. */
  userFor(token: string): Promise<User | null>;
  /** Ask Claude; returns [markdown, model that wrote it]. Throws DebriefError. */
  write(summary: Record<string, unknown>): Promise<[string, string]>;
  /** Save as this user (row-level security applies). */
  save(token: string, row: DebriefRow): Promise<void>;
  now?: () => number; // ms
}

export const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const MAX_BODY = 200_000; // bytes; a session summary is a few KB

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
const fail = (error: string, status: number) => json({ error }, status);

const text = (v: unknown) => typeof v === "string" && v.length > 0 && v.length <= 200;

export function parseEmails(raw: string | undefined): string[] {
  return (raw ?? "").split(/[,\s]+/).map((e) => e.trim().toLowerCase()).filter(Boolean);
}

export function makeHandler(deps: Deps): (req: Request) => Promise<Response> {
  return async (req) => {
    if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
    if (req.method !== "POST") return fail("Use POST.", 405);

    const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const user = token ? await deps.userFor(token) : null;
    if (!user) return fail("Sign in to the hub first.", 401);
    const allowed = !!user.email && deps.allowedEmails.includes(user.email.toLowerCase());

    const raw = await req.text();
    if (raw.length > MAX_BODY) return fail("That session is too big to send.", 413);
    let body: Record<string, unknown>;
    try {
      body = JSON.parse(raw || "{}");
    } catch {
      return fail("Bad request.", 400);
    }

    if (body.action === "status") return json({ configured: deps.apiKeySet, allowed });
    if (!allowed) return fail("This account isn't allowed to write debriefs (PITWALL_ALLOWED_EMAILS).", 403);
    if (!deps.apiKeySet) return fail("The Anthropic API key isn't set up in Supabase yet (README, AI debrief).", 503);

    const { game, car, track_key, summary } = body as { game: unknown; car: unknown; track_key: unknown; summary: unknown };
    if (!text(game) || !text(car) || !text(track_key)) return fail("Bad request.", 400);
    const session = (summary as { session?: { start?: unknown } } | null)?.session;
    if (!summary || typeof summary !== "object" || typeof session?.start !== "number") return fail("Bad request.", 400);

    let out: [string, string];
    try {
      out = await deps.write(summary as Record<string, unknown>);
    } catch (e) {
      if (e instanceof DebriefError) return fail(e.message, e.status);
      throw e;
    }
    const row: DebriefRow = {
      user_id: user.id,
      game: game as string,
      car: car as string,
      track_key: track_key as string,
      session_start: new Date((session.start as number) * 1000).toISOString(),
      body: out[0],
      model: out[1],
      created_at: new Date((deps.now ?? Date.now)()).toISOString(),
    };
    try {
      await deps.save(token, row);
    } catch (e) {
      return fail(`Couldn't save the debrief: ${e instanceof Error ? e.message : String(e)}`, 500);
    }
    return json(row);
  };
}
