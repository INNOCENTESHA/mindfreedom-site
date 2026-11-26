// Mind Freedom website assistant: a small Cloudflare Worker that answers visitors' questions
// with a language model. The API key is stored as the encrypted Worker secret AI_API_KEY and
// never appears in the website files.
//
// Works with a key from Anthropic (sk-ant-…), OpenAI (sk-…) or Google Gemini (AIza…); the
// provider is recognised from the key. Optional plain variables: AI_PROVIDER (anthropic | openai |
// gemini) to force one, and AI_MODEL to choose another model.
//
// Deploy: see deploy-assistant.ps1 in this folder.

const ALLOWED_ORIGINS = ["https://mindfreedom.co.tz", "https://www.mindfreedom.co.tz"];
const DEFAULT_MODEL = { anthropic: "claude-haiku-5-5", openai: "gpt-4o-mini", gemini: "gemini-2.0-flash" };
const MAX_MESSAGE = 600;   // characters per visitor message
const MAX_TURNS = 6;       // earlier messages sent along for context
const MAX_TOKENS = 350;

const SYSTEM = `You are the website assistant for Mind Freedom AI Consultancy (mindfreedom.co.tz),
founded by Innocent Pius Tesha, a civil, structural and GIS engineer based in Zanzibar, Tanzania,
working with clients worldwide.
Services: AI for engineering and GIS (QGIS, PostGIS, MIDAS Civil, STAAD.Pro, AutoCAD Civil 3D,
ArchiCAD); workflow automation (n8n, scheduled email-to-spreadsheet jobs, reports); academic and
research support; documents, reports and planning (Word, Excel, PDF, MS Project); custom tools and
AI connectors; training and workshops in English or Kiswahili.
Audiences: engineers and contractors; universities, lecturers and students; consultancies;
government and institutions; NGOs and small businesses.
How we work: 1) a free 30-60 minute discovery call, 2) a 1-2 week pilot on one real task with the
time saved measured, 3) deployment in 2-6 weeks, 4) training and ongoing support. The client keeps
every file, script and workflow.
Pricing: the first consultation is free; a written quote is sent before any work starts. Never state
or guess prices.
Contact: info@mindfreedom.co.tz, phone or WhatsApp +255 689 012 860, or the contact form on the page.
Rules: answer in the visitor's language, in at most four short sentences, plain text without
markdown. Be warm and concrete. If a question is outside these topics or you are unsure, say so and
point to WhatsApp or email. Do not give engineering, legal, medical or financial advice, and do not
invent projects, clients or results.`;

function corsFor(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

function json(data, status, cors) {
  return new Response(JSON.stringify(data), { status, headers: { ...cors, "content-type": "application/json" } });
}

function providerOf(key, forced) {
  if (forced) return String(forced).toLowerCase();
  if (/^sk-ant-/.test(key)) return "anthropic";
  if (/^AIza/.test(key)) return "gemini";
  if (/^sk-/.test(key)) return "openai";
  return "anthropic";
}

// keep a short, clean history: alternating user/assistant, plain strings, ending with the new question
function cleanHistory(history, message) {
  const out = [];
  for (const h of Array.isArray(history) ? history.slice(-MAX_TURNS) : []) {
    const role = h && h.role === "assistant" ? "assistant" : h && h.role === "user" ? "user" : null;
    const text = h && typeof h.text === "string" ? h.text.trim().slice(0, MAX_MESSAGE) : "";
    if (!role || !text) continue;
    if (out.length && out[out.length - 1].role === role) out[out.length - 1].text += "\n" + text;
    else out.push({ role, text });
  }
  while (out.length && out[0].role !== "user") out.shift();
  if (out.length && out[out.length - 1].role === "user") out.pop();
  out.push({ role: "user", text: message });
  return out;
}

async function askModel(provider, key, model, system, turns) {
  if (provider === "openai") {
    const r = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model, max_tokens: MAX_TOKENS,
        messages: [{ role: "system", content: system }, ...turns.map((t) => ({ role: t.role, content: t.text }))],
      }),
    });
    if (!r.ok) throw new Error(`openai ${r.status} ${(await r.text()).slice(0, 300)}`);
    const d = await r.json();
    return d.choices?.[0]?.message?.content || "";
  }
  if (provider === "gemini") {
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: turns.map((t) => ({ role: t.role === "assistant" ? "model" : "user", parts: [{ text: t.text }] })),
        generationConfig: { maxOutputTokens: MAX_TOKENS },
      }),
    });
    if (!r.ok) throw new Error(`gemini ${r.status} ${(await r.text()).slice(0, 300)}`);
    const d = await r.json();
    return (d.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join("");
  }
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({
      model, max_tokens: MAX_TOKENS, system,
      messages: turns.map((t) => ({ role: t.role, content: t.text })),
    }),
  });
  if (!r.ok) throw new Error(`anthropic ${r.status} ${(await r.text()).slice(0, 300)}`);
  const d = await r.json();
  return (d.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = ALLOWED_ORIGINS.includes(origin);
    const cors = corsFor(allowed ? origin : ALLOWED_ORIGINS[0]);
    const key = String(env.AI_API_KEY || "").trim();
    const provider = providerOf(key, env.AI_PROVIDER);

    // health check for the owner: says whether a key is set and which provider, never the key
    if (request.method === "GET") return json({ ok: true, keySet: Boolean(key), provider }, 200, cors);
    if (request.method === "OPTIONS") return new Response(null, { status: allowed ? 204 : 403, headers: cors });
    if (request.method !== "POST") return json({ error: "not found" }, 404, cors);
    if (!allowed) return json({ error: "forbidden" }, 403, cors);   // only the website may use it
    if (!key) return json({ error: "no key" }, 503, cors);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad request" }, 400, cors); }
    const message = String(body.message || "").trim().slice(0, MAX_MESSAGE);
    if (!message) return json({ error: "bad request" }, 400, cors);
    const lang = String(body.lang || "en").replace(/[^a-zA-Z-]/g, "").slice(0, 8) || "en";

    try {
      const reply = await askModel(provider, key, env.AI_MODEL || DEFAULT_MODEL[provider] || DEFAULT_MODEL.anthropic,
        SYSTEM + `\nThe visitor's page language code is "${lang}"; reply in that language unless they write in another.`,
        cleanHistory(body.history, message));
      if (!reply.trim()) throw new Error("empty reply");
      return json({ reply: reply.trim() }, 200, cors);
    } catch (e) {
      console.log("assistant error:", String(e && e.message || e));   // visible with `wrangler tail`
      return json({ error: "upstream" }, 502, cors);                  // the site then falls back to its built-in answers
    }
  },
};
