// OPTIONAL upgrade for the website assistant. Not deployed and not tested yet.
//
// The assistant on the site answers from a built-in list of topics. To let it answer
// free-form questions with a language model, deploy this file as a Cloudflare Worker,
// add your Anthropic API key as the secret ANTHROPIC_API_KEY, then put the Worker URL
// in content/site.json as "assistantEndpoint" and run `python3 build.py`.
// The key stays on the server; never put an API key in the website files.

const ALLOWED_ORIGIN = "https://mindfreedom.co.tz";
const MODEL = "claude-haiku-5-5";

const SYSTEM = `You are the website assistant for Mind Freedom AI Consultancy (mindfreedom.co.tz),
founded by Innocent Pius Tesha, a civil, structural and GIS engineer in Zanzibar, Tanzania.
Services: AI for engineering and GIS; workflow automation; academic and research support;
documents, reports and planning; custom tools and connectors; training and workshops.
Process: free discovery call, a pilot on one real task, deployment, then training and support.
Pricing: the first consultation is free; a quote is sent before any work starts. Never state prices.
Contact: info@mindfreedom.co.tz, phone or WhatsApp +255 689 012 860, or the contact form.
Answer in the visitor's language in at most four short sentences. If you are unsure, say so and
point to the contact details. Do not give engineering, legal or financial advice.`;

const cors = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST") return new Response("Not found", { status: 404 });
    let body;
    try { body = await request.json(); } catch { return new Response("Bad request", { status: 400, headers: cors }); }
    const message = String(body.message || "").slice(0, 600);
    if (!message) return new Response("Bad request", { status: 400, headers: cors });

    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 300,
        system: SYSTEM + `\nThe visitor's page language code is "${String(body.lang || "en").slice(0, 5)}".`,
        messages: [{ role: "user", content: message }],
      }),
    });
    if (!r.ok) return new Response(JSON.stringify({ error: "upstream" }), { status: 502, headers: { ...cors, "content-type": "application/json" } });
    const data = await r.json();
    const reply = (data.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
    return new Response(JSON.stringify({ reply }), { headers: { ...cors, "content-type": "application/json" } });
  },
};
