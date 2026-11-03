/**
 * Supabase Edge Function: writes an AI debrief for the hub, so you can get one
 * while the rig PC is off. The Anthropic API key lives here as a Supabase
 * secret (ANTHROPIC_API_KEY), never in the browser.
 *
 * Deployed by .github/workflows/functions.yml.
 */
import Anthropic from "npm:@anthropic-ai/sdk@1.2.0";
import { createClient } from "npm:@supabase/supabase-js@2.118.0";
import { DebriefError, makeHandler, parseEmails } from "./handler.ts";
import { MODEL, SYSTEM } from "./prompt.ts";

const url = Deno.env.get("SUPABASE_URL")!;
const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
const apiKey = Deno.env.get("ANTHROPIC_API_KEY") ?? "";

const asUser = (token: string) =>
  createClient(url, anon, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });

async function write(summary: Record<string, unknown>): Promise<[string, string]> {
  const client = new Anthropic({ apiKey, timeout: 120_000, maxRetries: 1 });
  let resp;
  try {
    resp = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 4000,
      // If a safety check declines the request, the API retries it on the
      // model Anthropic recommends for that case, in the same call.
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      output_config: { effort: "medium" },
      system: SYSTEM,
      messages: [{ role: "user", content: "Session data (JSON):\n" + JSON.stringify(summary, null, 1) }],
    });
  } catch (e) {
    if (e instanceof Anthropic.AuthenticationError) throw new DebriefError("The Anthropic API key in Supabase wasn't accepted.");
    if (e instanceof Anthropic.RateLimitError) throw new DebriefError("Anthropic says slow down (rate limit). Try again in a minute.", 429);
    if (e instanceof Anthropic.BadRequestError) {
      const msg = e.message;
      if (/credit|billing/i.test(msg)) throw new DebriefError("Your Anthropic account is out of credit.", 402);
      throw new DebriefError(`Anthropic rejected the request: ${msg}`);
    }
    if (e instanceof Anthropic.APIConnectionError) throw new DebriefError("Couldn't reach Anthropic. Try again later.");
    if (e instanceof Anthropic.APIError) throw new DebriefError(`Anthropic had a problem (${e.status}). Try again later.`);
    throw e;
  }
  if (resp.stop_reason === "refusal") throw new DebriefError("Claude declined to write this one.");
  const text = resp.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("").trim();
  if (!text) throw new DebriefError("Claude sent back an empty debrief.");
  return [text, resp.model];
}

Deno.serve(
  makeHandler({
    apiKeySet: apiKey.length > 0,
    allowedEmails: parseEmails(Deno.env.get("PITWALL_ALLOWED_EMAILS")),
    async userFor(token) {
      const { data, error } = await asUser(token).auth.getUser(token);
      return error || !data.user ? null : { id: data.user.id, email: data.user.email ?? null };
    },
    write,
    async save(token, row) {
      const { error } = await asUser(token).from("debriefs")
        .upsert(row, { onConflict: "user_id,game,car,track_key,session_start" });
      if (error) throw new Error(error.message);
    },
  }),
);
