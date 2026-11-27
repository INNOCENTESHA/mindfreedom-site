// Mind Freedom agents: one Cloudflare Worker that runs the website's AI agents.
//
//  1. Chat assistant + lead agent   POST /          visitors ask questions; when a visitor shares a name,
//                                                   a contact and a task, the lead is emailed to the owner
//                                                   and the Google Calendar booking link is offered
//  2. Pilot-proposal agent          (inside chat)   a described weekly task gets a short pilot plan
//  3. Enquiry follow-up agent       POST /enquiry   the contact form's message gets a drafted reply in the
//                                                   visitor's language, emailed to the owner with a send link
//  4. Watchdog                      cron 3-hourly   site up, Meta Pixel present, assistant connected,
//                                                   AI answering; emails when something changes
//  5. Daily ads report              cron 17:02 EAT  reads Meta Ads results (needs META_TOKEN) and emails a
//                                                   Problem / Why / Solution report
//  6. Calendar booking agent        POST /slots     free times from the owner's Google Calendar
//                                   POST /book      books one into the calendar with a Google Meet link and
//                                                   sends the visitor Google's invitation
//                                   GET /gcal/connect  one-time: the owner allows calendar access
//
// Settings (Cloudflare > Worker > Settings > Variables and secrets):
//   AI_API_KEY (secret)       Gemini / Anthropic / OpenAI key     AI_PROVIDER, AI_MODEL   provider and model
//   AI_SEARCH = "off"         stop Gemini using Google Search     BOOKING_URL             Google Calendar booking page
//   NOTIFY_EMAIL              address that receives alerts (required for any email)
//   NOTIFY_CC                 optional second address (copy)
//   MAILER (Send email binding) sends alerts to a verified address; MAIL_FROM optional (default agents@mindfreedom.co.tz)
//   META_TOKEN (secret), META_AD_ACCOUNT, META_API_VERSION       for the ads report
//   STATE (KV binding)           watchdog memory, and stores the calendar connection
//   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (secret)   Google sign-in key for the calendar agent
//   CAL_OWNER (default NOTIFY_CC)  only this Google account may connect its calendar
//   CAL_HOURS "9-17", CAL_DAYS "1,2,3,4,5", CAL_SLOT_MIN 60, CAL_NOTICE_HOURS 12, CAL_DAYS_AHEAD 14 (East Africa Time)
// Emails are sent through FormSubmit (formsubmit.co), the same service as the site's contact form.
// The API keys never appear in the website files or in any reply.

import { EmailMessage } from "cloudflare:email";

const SITE = "https://mindfreedom.co.tz";
const ALLOWED_ORIGINS = [SITE, "https://www.mindfreedom.co.tz"];
const DEFAULT_MODEL = { anthropic: "claude-haiku-5-5", openai: "gpt-4o-mini", gemini: "gemini-3.8-flash" };
const MAX_MESSAGE = 600;
const MAX_TURNS = 8;
const MAX_TOKENS = 450;
const LEAD_TAG = "[[LEAD";
const LEAD_SIGNAL = "\u001eLEAD";   // tells the page a lead was recorded; the page removes it before showing text

const ABOUT = `Mind Freedom AI Consultancy (mindfreedom.co.tz), founded by a civil, structural and GIS
engineer based in Zanzibar, Tanzania, working with clients worldwide.
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
Contact: the email, phone/WhatsApp (+255 689 012 860) and contact form shown on the page.
Case studies (client names withheld): HDPE culvert encasements checked by 3D finite element analysis
in MIDAS Civil with Word reports and AutoCAD drawings; a self-updating QGIS road atlas for two road
contracts (228.7 km, daily PDF export); RFI (inspection request) logging automated from email into
spreadsheets; a five-storey parking structure modelled in ArchiCAD next to a World Heritage site; a
549-day construction programme in MS Project; "The Thirsty Cloud" story map (RCMRD Arts & Maps 2026);
a residential RC building modelled in STAAD.Pro with a drawing set; an Excel VBA design tool for
thermoplastic culverts (AASHTO LRFD 12.12); a daily weather advisory for road works built in n8n;
AI connectors that drive engineering software on an office PC.`;

function chatSystem(env, lang, today, leadSent, calReady) {
  const booking = calReady
    ? `Visitors book the free discovery call right here in the chat: as soon as you have sent the LEAD line, the page shows free
times from the owner's calendar under your reply, so tell them to pick one there (a "Book a call" button also does it).${env.BOOKING_URL ? ` If that does not suit them, they can use this booking page: ${env.BOOKING_URL}` : ""}`
    : env.BOOKING_URL
    ? `To book the free discovery call, give this booking page: ${env.BOOKING_URL}`
    : "To book the free discovery call, say the team will reply within one working day to arrange a time.";
  return `You are the website assistant and first contact for ${ABOUT}

Rules: answer in the visitor's language, in at most five short sentences, plain text without markdown.
Be warm and concrete and always put things in your own fresh words fitted to what this visitor asked;
never recite a fixed list. When a visitor sends only a topic word such as "Services", "How we work",
"Pricing" or "Contact", give a short natural overview of that topic and offer one helpful next step.
If a question needs current information, use Google Search when it is available and say briefly where
it comes from. If unsure or outside these topics, say so and point to WhatsApp or email. Do not give
engineering, legal, medical or financial advice, and do not invent projects, clients or results.

Pilot plans: when a visitor describes a task they do repeatedly, reply with a short pilot plan in
plain sentences: what would be automated, the 2-4 steps, the tools involved and a realistic pilot
length of 1-2 weeks. Never give prices. Then offer the free discovery call.

Leads: when a visitor wants help, a call or a quote, kindly ask (over one or two turns, not all at
once) for their name, an email or WhatsApp number, their organisation and country, and the task.
${booking}
${leadSent
    ? "This visitor's details were already recorded; do not output the LEAD line again."
    : `As soon as you know at least the name, a way to contact them (email or phone) and the task, end
your reply with ONE extra final line, exactly in this form and nothing after it (the visitor never sees it):
${LEAD_TAG} {"name":"…","contact":"…","organisation":"…","country":"…","task":"…","pilot":"one-sentence pilot idea"}]]
Use "" for anything unknown. Never output that line in any other case.`}

Today's date is ${today}. The visitor's page language code is "${lang}"; reply in that language unless
they write in another.`;
}

/* ---------------------------------------------------------------- helpers */

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
  if (/^AIza/.test(key) || /^AQ\./.test(key)) return "gemini";
  if (/^sk-/.test(key)) return "openai";
  return "anthropic";
}

function aiConfig(env) {
  const key = String(env.AI_API_KEY || "").trim();
  const provider = providerOf(key, env.AI_PROVIDER);
  const model = env.AI_MODEL || DEFAULT_MODEL[provider] || DEFAULT_MODEL.anthropic;
  return { key, provider, model };
}

const clip = (v, n) => String(v == null ? "" : v).trim().slice(0, n);

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

function splitLead(text) {
  const i = text.indexOf(LEAD_TAG);
  if (i < 0) return { visible: text, lead: null };
  const raw = text.slice(i + LEAD_TAG.length);
  const end = raw.lastIndexOf("]]");
  let lead = null;
  try { lead = JSON.parse((end >= 0 ? raw.slice(0, end) : raw).trim()); } catch { lead = null; }
  return { visible: text.slice(0, i).trimEnd(), lead };
}

function leadInfo(l) {
  const c = clip(l.contact, 160);
  const email = (c.match(/[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+/) || [""])[0];
  return { name: clip(l.name, 120), email, task: clip(l.task, 300), organisation: clip(l.organisation, 160) };
}

function validLead(l) {
  return Boolean(l && typeof l === "object" && clip(l.name, 120) && clip(l.contact, 160) && clip(l.task, 1000));
}

/* ---------------------------------------------------------------- model calls */

function geminiCall(cfg, system, turns, opts, stream) {
  const body = {
    systemInstruction: { parts: [{ text: system }] },
    contents: turns.map((t) => ({ role: t.role === "assistant" ? "model" : "user", parts: [{ text: t.text }] })),
    generationConfig: { maxOutputTokens: (opts && opts.maxTokens) || MAX_TOKENS },
  };
  if (opts && opts.search) body.tools = [{ google_search: {} }];
  const verb = stream ? "streamGenerateContent?alt=sse" : "generateContent";
  return fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(cfg.model)}:${verb}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-goog-api-key": cfg.key },
    body: JSON.stringify(body),
  });
}

const BUSY = [429, 500, 503, 504];
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function geminiStream(cfg, system, turns, opts) {
  let r = await geminiCall(cfg, system, turns, opts, true);
  if (!r.ok && BUSY.includes(r.status)) { await pause(1200); r = await geminiCall(cfg, system, turns, opts, true); }
  if (!r.ok || !r.body) throw new Error(`gemini ${r.status} ${(await r.text()).slice(0, 300)}`);
  const dec = new TextDecoder(), enc = new TextEncoder();
  let buf = "";
  return r.body.pipeThrough(new TransformStream({
    transform(chunk, ctl) {
      buf += dec.decode(chunk, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        try {
          const d = JSON.parse(line.slice(5));
          const text = (d.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join("");
          if (text) ctl.enqueue(enc.encode(text));
        } catch { /* partial line */ }
      }
    },
  }));
}

async function askModel(cfg, system, turns, opts) {
  const { provider, key, model } = cfg;
  const maxTokens = (opts && opts.maxTokens) || MAX_TOKENS;
  if (provider === "openai") {
    const r = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
      body: JSON.stringify({ model, max_tokens: maxTokens,
        messages: [{ role: "system", content: system }, ...turns.map((t) => ({ role: t.role, content: t.text }))] }),
    });
    if (!r.ok) throw new Error(`openai ${r.status} ${(await r.text()).slice(0, 300)}`);
    const d = await r.json();
    return d.choices?.[0]?.message?.content || "";
  }
  if (provider === "gemini") {
    const r = await geminiCall(cfg, system, turns, opts, false);
    if (!r.ok) throw new Error(`gemini ${r.status} ${(await r.text()).slice(0, 300)}`);
    const d = await r.json();
    return (d.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join("");
  }
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: turns.map((t) => ({ role: t.role, content: t.text })) }),
  });
  if (!r.ok) throw new Error(`anthropic ${r.status} ${(await r.text()).slice(0, 300)}`);
  const d = await r.json();
  return (d.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
}

async function askWithRetry(cfg, system, turns, opts) {
  try { return await askModel(cfg, system, turns, opts); }
  catch (e) {
    if (!/ (429|500|503|504|524) /.test(String(e && e.message))) throw e;
    await pause(1200);
    return askModel(cfg, system, turns, opts);
  }
}

/* ---------------------------------------------------------------- email (addresses come from settings) */

// Emails go through Cloudflare's "Send email" binding (MAILER) to a verified address;
// FormSubmit is only a fallback, because it rate-limits sends from Cloudflare's servers.
function b64(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function rawEmail(from, to, subject, text) {
  const body = b64(text).replace(/.{1,76}/g, "$&\r\n");
  return [
    `From: Mind Freedom agents <${from}>`,
    `To: <${to}>`,
    `Subject: =?UTF-8?B?${b64(subject)}?=`,
    `Date: ${new Date().toUTCString()}`,
    `Message-ID: <${crypto.randomUUID()}@mindfreedom.co.tz>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
    "",
    body,
  ].join("\r\n");
}

async function notify(env, subject, fields) {
  const text = Object.entries(fields).filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}:\n${v}`).join("\n\n") + "\n\n(Sent by the Mind Freedom website agents.)";
  if (env.MAILER) {
    const from = env.MAIL_FROM || "agents@mindfreedom.co.tz";
    const targets = [env.MAIL_TO, env.NOTIFY_CC, env.NOTIFY_EMAIL].map((x) => String(x || "").trim()).filter(Boolean);
    for (const to of [...new Set(targets)]) {
      try { await env.MAILER.send(new EmailMessage(from, to, rawEmail(from, to, subject, text))); return true; }
      catch (e) { console.log("mailer failed for one address:", String(e && e.message || e).slice(0, 200)); }
    }
  }
  const to = String(env.NOTIFY_EMAIL || "").trim();
  if (!to) { console.log("notify skipped: no MAILER binding and no NOTIFY_EMAIL"); return false; }
  const body = { _subject: subject, _template: "box", _captcha: "false", ...fields };
  if (env.NOTIFY_CC) body._cc = String(env.NOTIFY_CC).trim();
  try {
    const r = await fetch(`https://formsubmit.co/ajax/${encodeURIComponent(to)}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", origin: SITE, referer: SITE + "/" },
      body: JSON.stringify(body),
    });
    const t = await r.text();
    const ok = r.ok && /"success"\s*:\s*"?true/.test(t);
    if (!ok) console.log("notify failed:", r.status, t.slice(0, 200));
    return ok;
  } catch (e) { console.log("notify error:", String(e)); return false; }
}

function sendLead(env, lead, lang, turns) {
  const t = turns.slice(-6).map((x) => `${x.role === "user" ? "Visitor" : "Assistant"}: ${x.text}`).join("\n");
  return notify(env, `New lead from the website: ${clip(lead.name, 80)}`, {
    Name: clip(lead.name, 120), Contact: clip(lead.contact, 160), Organisation: clip(lead.organisation, 160),
    Country: clip(lead.country, 80), Task: clip(lead.task, 1000), "Pilot idea": clip(lead.pilot, 400),
    "Page language": lang, Conversation: clip(t, 3000),
  });
}

/* ---------------------------------------------------------------- 1+2. chat, leads and pilot plans */

function leadFilter(onLead) {
  const enc = new TextEncoder(), dec = new TextDecoder();
  let pending = "", captured = null;
  return new TransformStream({
    transform(chunk, ctl) {
      const s = dec.decode(chunk, { stream: true });
      if (captured !== null) { captured += s; return; }
      pending += s;
      const i = pending.indexOf(LEAD_TAG);
      if (i >= 0) {
        if (i > 0) ctl.enqueue(enc.encode(pending.slice(0, i)));
        captured = pending.slice(i); pending = ""; return;
      }
      let keep = 0;
      for (let k = Math.min(LEAD_TAG.length - 1, pending.length); k > 0; k--) {
        if (LEAD_TAG.startsWith(pending.slice(-k))) { keep = k; break; }
      }
      const out = pending.slice(0, pending.length - keep);
      if (out) ctl.enqueue(enc.encode(out));
      pending = pending.slice(pending.length - keep);
    },
    flush(ctl) {
      if (captured === null) { if (pending) ctl.enqueue(enc.encode(pending)); return; }
      const { lead } = splitLead(captured);
      if (validLead(lead)) { onLead(lead); ctl.enqueue(enc.encode(LEAD_SIGNAL + JSON.stringify(leadInfo(lead)))); }
    },
  });
}

async function handleChat(request, env, ctx, cors) {
  const cfg = aiConfig(env);
  if (!cfg.key) return json({ error: "no key" }, 503, cors);
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad request" }, 400, cors); }
  const message = clip(body.message, MAX_MESSAGE);
  if (!message) return json({ error: "bad request" }, 400, cors);
  const lang = String(body.lang || "en").replace(/[^a-zA-Z-]/g, "").slice(0, 8) || "en";
  const system = chatSystem(env, lang, new Date().toISOString().slice(0, 10), Boolean(body.leadSent), await calendarReady(env));
  const turns = cleanHistory(body.history, message);
  const opts = { search: cfg.provider === "gemini" && String(env.AI_SEARCH || "on").toLowerCase() !== "off" };
  const onLead = (lead) => { ctx.waitUntil(sendLead(env, lead, lang, turns)); };

  try {
    if (body.stream && cfg.provider === "gemini") {
      const stream = (await geminiStream(cfg, system, turns, opts)).pipeThrough(leadFilter(onLead));
      return new Response(stream, { headers: { ...cors, "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
    }
    const raw = await askWithRetry(cfg, system, turns, opts);
    const { visible, lead } = splitLead(raw);
    if (!visible.trim()) throw new Error("empty reply");
    const got = validLead(lead);
    if (got) onLead(lead);
    return json({ reply: visible.trim(), lead: got, leadInfo: got ? leadInfo(lead) : undefined }, 200, cors);
  } catch (e) {
    console.log("assistant error:", String(e && e.message || e));
    return json({ error: "upstream" }, 502, cors);   // the site then falls back to its built-in answers
  }
}

/* ---------------------------------------------------------------- 3. enquiry follow-up */

function mailto(to, subject, text) {
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text.slice(0, 1600))}`;
}

async function draftEnquiryReply(env, e) {
  const cfg = aiConfig(env);
  const system = `You write email replies on behalf of ${ABOUT}

Write a reply to the website enquiry below, signed "Mind Freedom AI Consultancy".
Write in the language the visitor wrote in (page language code "${e.lang}"). Plain text, no markdown,
under 170 words. Thank them, restate their task in one sentence, mention the single most relevant
case study in one sentence, propose the free 30-60 minute discovery call${env.BOOKING_URL ? ` with this booking link: ${env.BOOKING_URL}` : ""},
and say a short pilot on one real task is the usual first step. Never state prices. Start with the
greeting line; no subject line.`;
  const text = `Name: ${e.name}\nEmail: ${e.email}\nOrganisation: ${e.organisation}\nInterested in: ${e.topic}\nMessage: ${e.message}`;
  return (await askWithRetry(cfg, system, [{ role: "user", text }], { maxTokens: 500 })).trim();
}

async function handleEnquiry(request, env, ctx, cors) {
  let b;
  try { b = await request.json(); } catch { return json({ error: "bad request" }, 400, cors); }
  const e = {
    name: clip(b.name, 120), email: clip(b.email, 160), organisation: clip(b.organisation, 160),
    topic: clip(b.topic, 120), message: clip(b.message, 2000),
    lang: String(b.lang || "en").replace(/[^a-zA-Z-]/g, "").slice(0, 8) || "en",
  };
  if (!e.name || !e.message || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.email)) return json({ error: "bad request" }, 400, cors);
  ctx.waitUntil((async () => {
    let draft = "";
    try { draft = await draftEnquiryReply(env, e); } catch (err) { console.log("enquiry draft error:", String(err && err.message || err)); }
    await notify(env, `Enquiry from ${e.name}: draft reply ready`, {
      Name: e.name, Email: e.email, Organisation: e.organisation, "Interested in": e.topic,
      Message: e.message, "Page language": e.lang,
      "Draft reply": draft || "(the AI could not draft a reply this time; please reply directly)",
      "Send it": draft ? `Open this link to send the draft from your mail app (edit first if you like): ${mailto(e.email, "Re: your enquiry to Mind Freedom AI Consultancy", draft)}` : "",
    });
  })());
  return json({ ok: true }, 202, cors);
}

/* ---------------------------------------------------------------- 4. watchdog */

async function runWatchdog(env, selfUrl) {
  const problems = [], fine = [];
  try {
    const r = await fetch(SITE + "/?watchdog=" + Date.now(), { headers: { "user-agent": "MindFreedom-Watchdog" } });
    const html = await r.text();
    if (!r.ok) problems.push(`Website returned HTTP ${r.status}.`);
    else {
      fine.push("Website loads.");
      if (!/fbq\(\s*['"]init['"]/.test(html)) problems.push("The Meta Pixel code is missing from the page, so ad landing page views are not counted.");
      else fine.push("Meta Pixel present.");
      const host = new URL(selfUrl).host;
      if (!html.includes(host)) problems.push("The website's assistant is not connected to this server (assistantEndpoint missing).");
      else fine.push("Assistant connected.");
    }
  } catch (e) { problems.push(`Website could not be reached: ${String(e && e.message || e)}`); }

  const cfg = aiConfig(env);
  if (!cfg.key) problems.push("No AI key is set on the server (AI_API_KEY).");
  else {
    try {
      await askModel(cfg, "Reply with the single word OK.", [{ role: "user", text: "ping" }], { maxTokens: 5 });
      fine.push(`AI (${cfg.provider} ${cfg.model}) answering.`);
    } catch (e) {
      const m = String(e && e.message || e);
      if (/ 429 /.test(m)) problems.push(`The AI key's quota is used up (${cfg.provider} 429), so the assistant shows built-in answers. Fix: turn on billing or wait for the quota to reset${cfg.provider === "gemini" ? " in Google AI Studio" : ""}.`);
      else if (/ 40[13] /.test(m)) problems.push(`The AI key was rejected. Check AI_API_KEY in Cloudflare. Detail: ${m.slice(0, 120)}`);
      else if (/ 404 /.test(m)) problems.push(`The AI model was not found (${cfg.model}). Update AI_MODEL in Cloudflare.`);
      else problems.push(`The AI is not answering: ${m.slice(0, 200)}`);
    }
  }

  const status = problems.length ? "problem: " + problems.join(" | ") : "ok";
  let previous = null;
  if (env.STATE) { try { previous = await env.STATE.get("watchdog"); await env.STATE.put("watchdog", status); } catch { previous = null; } }
  // without KV memory: email on every check that finds a problem; with KV: only when the status changes
  const shouldSend = env.STATE ? previous !== status && (problems.length > 0 || previous !== null) : problems.length > 0;
  if (shouldSend) {
    await notify(env, problems.length ? `Website alert: ${problems.length} problem(s) on mindfreedom.co.tz` : "Website recovered: mindfreedom.co.tz is working again", {
      Problems: problems.join("\n") || "None", Working: fine.join("\n"), "Checked at": new Date().toISOString(),
    });
  }
  return { problems, fine, emailed: shouldSend };
}

/* ---------------------------------------------------------------- 5. daily ads report */

function lpv(actions) {
  const a = (actions || []).find((x) => x.action_type === "landing_page_view");
  return a ? Number(a.value) : 0;
}

async function metaGet(env, path, params) {
  const v = env.META_API_VERSION || "v24.0";
  const u = new URL(`https://graph.facebook.com/${v}/${path}`);
  for (const [k, val] of Object.entries(params)) u.searchParams.set(k, val);
  const r = await fetch(u, { headers: { authorization: `Bearer ${env.META_TOKEN}` } });
  const t = await r.text();
  if (!r.ok) throw new Error(`meta ${r.status} ${t.slice(0, 300)}`);
  return JSON.parse(t).data || [];
}

async function runAdsReport(env) {
  if (!env.META_TOKEN) { console.log("ads report skipped: META_TOKEN not set"); return { skipped: true }; }
  const acct = `act_${String(env.META_AD_ACCOUNT || "2139187990164986").replace(/^act_/, "")}`;
  const fields = "campaign_name,spend,impressions,reach,frequency,cpm,inline_link_clicks,ctr,actions";
  let data;
  try {
    const [yesterday, lifetime, countries, ages] = await Promise.all([
      metaGet(env, `${acct}/insights`, { level: "campaign", date_preset: "yesterday", fields }),
      metaGet(env, `${acct}/insights`, { level: "campaign", date_preset: "maximum", fields }),
      metaGet(env, `${acct}/insights`, { date_preset: "yesterday", breakdowns: "country", fields: "spend,impressions,inline_link_clicks,actions", limit: "50" }),
      metaGet(env, `${acct}/insights`, { date_preset: "yesterday", breakdowns: "age", fields: "spend,impressions,inline_link_clicks,actions" }),
    ]);
    const slim = (rows, key) => rows.map((r) => ({
      [key]: r[key] || r.campaign_name, spend: +r.spend || 0, impressions: +r.impressions || 0,
      reach: r.reach ? +r.reach : undefined, link_clicks: +r.inline_link_clicks || 0, landing_page_views: lpv(r.actions),
      cpm: r.cpm ? +r.cpm : undefined, frequency: r.frequency ? +r.frequency : undefined,
    }));
    data = { yesterday: slim(yesterday, "campaign_name"), lifetime: slim(lifetime, "campaign_name"),
      countries_yesterday: slim(countries, "country").sort((a, b) => b.spend - a.spend).slice(0, 15),
      ages_yesterday: slim(ages, "age") };
  } catch (e) {
    const m = String(e && e.message || e);
    await notify(env, "Daily ads report: could not read Meta Ads", { Problem: m, Fix: "Check META_TOKEN (it may have expired) and META_AD_ACCOUNT in Cloudflare." });
    return { error: m };
  }

  let report = "";
  try {
    report = (await askWithRetry(aiConfig(env), `You are a Meta Ads analyst for ${ABOUT}
The goal is the most landing page views from the worldwide traffic campaign, then enquiries.
Write a short plain-text daily report (no markdown tables): a 3-line snapshot of yesterday vs lifetime,
then up to 5 findings each as "Problem / Why / Solution" with the numbers, then a prioritised action
list for today. Label estimates as estimates. Use only the numbers given; never invent figures.`,
      [{ role: "user", text: JSON.stringify(data) }], { maxTokens: 1200 })).trim();
  } catch (e) { report = `(AI summary unavailable: ${String(e && e.message || e).slice(0, 160)})`; }

  const y = data.yesterday.reduce((s, r) => ({ spend: s.spend + r.spend, lpv: s.lpv + r.landing_page_views, clicks: s.clicks + r.link_clicks, imp: s.imp + r.impressions }), { spend: 0, lpv: 0, clicks: 0, imp: 0 });
  await notify(env, `Daily ads report: ${y.lpv} landing page views yesterday for $${y.spend.toFixed(2)}`, {
    Yesterday: `Spent $${y.spend.toFixed(2)} | impressions ${y.imp} | link clicks ${y.clicks} | landing page views ${y.lpv}`,
    Report: report,
    "Top countries (yesterday)": data.countries_yesterday.map((c) => `${c.country}: ${c.landing_page_views} views, $${c.spend.toFixed(2)}, ${c.impressions} impr.`).join("\n"),
  });
  return { sent: true };
}

/* ---------------------------------------------------------------- 6. calendar booking agent */

const CAL_TZ = "Africa/Dar_es_Salaam";
const CAL_OFFSET = 3 * 3600e3;            // East Africa Time, no daylight saving
const GCAL_SCOPES = "openid email https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.freebusy";
let tokenCache = { token: "", until: 0 };

function calCfg(env) {
  const [h0, h1] = String(env.CAL_HOURS || "9-17").split("-").map((x) => parseInt(x, 10));
  return {
    id: env.CAL_ID || "primary",
    startHour: Number.isFinite(h0) ? h0 : 9, endHour: Number.isFinite(h1) ? h1 : 17,
    days: String(env.CAL_DAYS || "1,2,3,4,5").split(",").map((x) => parseInt(x, 10)),
    minutes: parseInt(env.CAL_SLOT_MIN || "60", 10) || 60,
    noticeMs: (parseFloat(env.CAL_NOTICE_HOURS || "12") || 0) * 3600e3,
    daysAhead: parseInt(env.CAL_DAYS_AHEAD || "14", 10) || 14,
  };
}

async function refreshToken(env) {
  if (env.GOOGLE_REFRESH_TOKEN) return env.GOOGLE_REFRESH_TOKEN;
  if (!env.STATE) return "";
  try { return (await env.STATE.get("gcal_refresh")) || ""; } catch { return ""; }
}

async function calendarReady(env) {
  return Boolean(env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET && await refreshToken(env));
}

async function googleToken(env) {
  if (tokenCache.token && Date.now() < tokenCache.until) return tokenCache.token;
  const refresh = await refreshToken(env);
  if (!refresh || !env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET) throw new Error("calendar not connected");
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refresh, client_id: env.GOOGLE_CLIENT_ID, client_secret: env.GOOGLE_CLIENT_SECRET }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.access_token) throw new Error(`google token ${r.status} ${d.error || ""} ${d.error_description || ""}`.trim());
  tokenCache = { token: d.access_token, until: Date.now() + Math.max(60, (d.expires_in || 3600) - 120) * 1000 };
  return tokenCache.token;
}

async function gcal(env, method, path, body) {
  const r = await fetch(`https://www.googleapis.com/calendar/v3/${path}`, {
    method, headers: { authorization: `Bearer ${await googleToken(env)}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const t = await r.text();
  if (!r.ok) throw new Error(`calendar ${r.status} ${t.slice(0, 300)}`);
  return t ? JSON.parse(t) : {};
}

// every possible start time (UTC ms) in the booking window, on the hour grid, in East Africa Time
function candidateStarts(cfg, now) {
  const out = [];
  const local = new Date(now + CAL_OFFSET);
  const y = local.getUTCFullYear(), m = local.getUTCMonth(), d0 = local.getUTCDate();
  for (let d = 0; d <= cfg.daysAhead; d++) {
    const day = new Date(Date.UTC(y, m, d0 + d));
    if (!cfg.days.includes(day.getUTCDay())) continue;
    for (let mins = cfg.startHour * 60; mins + cfg.minutes <= cfg.endHour * 60; mins += cfg.minutes) {
      const start = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 0, mins) - CAL_OFFSET;
      if (start >= now + cfg.noticeMs) out.push(start);
    }
  }
  return out;
}

async function busyTimes(env, cfg, from, to) {
  const d = await gcal(env, "POST", "freeBusy", { timeMin: new Date(from).toISOString(), timeMax: new Date(to).toISOString(), items: [{ id: cfg.id }] });
  const cal = d.calendars && (d.calendars[cfg.id] || Object.values(d.calendars)[0]);
  if (cal && cal.errors && cal.errors.length) throw new Error("calendar freeBusy " + JSON.stringify(cal.errors).slice(0, 200));
  return ((cal && cal.busy) || []).map((b) => [Date.parse(b.start), Date.parse(b.end)]);
}

async function freeSlots(env, now = Date.now(), max = 6, perDay = 2) {
  const cfg = calCfg(env);
  const starts = candidateStarts(cfg, now);
  if (!starts.length) return [];
  const len = cfg.minutes * 60e3;
  const busy = await busyTimes(env, cfg, starts[0], starts[starts.length - 1] + len);
  const out = [], days = {};
  for (const s of starts) {
    if (busy.some(([a, b]) => s < b && s + len > a)) continue;
    const day = new Date(s + CAL_OFFSET).toISOString().slice(0, 10);
    if ((days[day] = (days[day] || 0) + 1) > perDay) continue;
    out.push({ start: new Date(s).toISOString(), end: new Date(s + len).toISOString() });
    if (out.length >= max) break;
  }
  return out;
}

async function handleSlots(env, cors) {
  if (!(await calendarReady(env))) return json({ ready: false, slots: [], bookingUrl: env.BOOKING_URL || "" }, 200, cors);
  try { return json({ ready: true, slots: await freeSlots(env), tz: CAL_TZ, bookingUrl: env.BOOKING_URL || "" }, 200, cors); }
  catch (e) { console.log("slots error:", String(e && e.message || e)); return json({ ready: false, slots: [], bookingUrl: env.BOOKING_URL || "" }, 200, cors); }
}

// daily limits count successful bookings only
async function overLimit(env, key, limit) {
  if (!env.STATE) return false;
  try { return parseInt((await env.STATE.get(key)) || "0", 10) >= limit; } catch { return false; }
}

async function countBooking(env, key) {
  if (!env.STATE) return;
  try { await env.STATE.put(key, String(parseInt((await env.STATE.get(key)) || "0", 10) + 1), { expirationTtl: 86400 }); } catch { /* ignore */ }
}

async function handleBook(request, env, ctx, cors) {
  let b;
  try { b = await request.json(); } catch { return json({ error: "bad request" }, 400, cors); }
  const v = {
    start: String(b.start || ""), name: clip(b.name, 120), email: clip(b.email, 160).toLowerCase(),
    organisation: clip(b.organisation, 160), task: clip(b.task, 600), lang: String(b.lang || "en").replace(/[^a-zA-Z-]/g, "").slice(0, 8) || "en",
  };
  if (!v.name || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email) || !Date.parse(v.start)) return json({ error: "bad request" }, 400, cors);
  if (!(await calendarReady(env))) return json({ error: "not ready", bookingUrl: env.BOOKING_URL || "" }, 503, cors);
  const ip = request.headers.get("CF-Connecting-IP") || "?";
  if (await overLimit(env, `book:ip:${ip}`, 3) || await overLimit(env, `book:mail:${v.email}`, 2)) return json({ error: "limit" }, 429, cors);

  const cfg = calCfg(env), len = cfg.minutes * 60e3, start = Date.parse(v.start);
  if (!candidateStarts(cfg, Date.now()).includes(start)) return json({ error: "taken" }, 409, cors);
  try {
    const busy = await busyTimes(env, cfg, start, start + len);
    if (busy.some(([a, z]) => start < z && start + len > a)) return json({ error: "taken" }, 409, cors);
    const desc = ["Booked through the mindfreedom.co.tz website assistant.", "", `Name: ${v.name}`, `Email: ${v.email}`]
      .concat(v.organisation ? [`Organisation: ${v.organisation}`] : [], v.task ? [`Task: ${v.task}`] : [], [`Page language: ${v.lang}`]).join("\n");
    const ev = await gcal(env, "POST", `calendars/${encodeURIComponent(cfg.id)}/events?conferenceDataVersion=1&sendUpdates=all`, {
      summary: `Mind Freedom AI Consultancy – Consultation (${v.name})`,
      description: desc,
      start: { dateTime: new Date(start).toISOString(), timeZone: CAL_TZ },
      end: { dateTime: new Date(start + len).toISOString(), timeZone: CAL_TZ },
      attendees: [{ email: v.email, displayName: v.name }],
      conferenceData: { createRequest: { requestId: crypto.randomUUID(), conferenceSolutionKey: { type: "hangoutsMeet" } } },
      reminders: { useDefault: true },
      guestsCanInviteOthers: false,
    });
    const meet = ev.hangoutLink || (ev.conferenceData && ev.conferenceData.entryPoints && (ev.conferenceData.entryPoints.find((p) => p.entryPointType === "video") || {}).uri) || "";
    ctx.waitUntil(Promise.all([countBooking(env, `book:ip:${ip}`), countBooking(env, `book:mail:${v.email}`)]));
    const eat = new Date(start + CAL_OFFSET).toISOString().replace("T", " ").slice(0, 16) + " EAT";
    ctx.waitUntil(notify(env, `New booking: ${v.name}, ${eat}`, {
      When: eat, Name: v.name, Email: v.email, Organisation: v.organisation, Task: v.task, "Google Meet": meet,
      Note: "The event is in your Google Calendar and Google has sent the visitor an invitation.",
    }));
    return json({ ok: true, start: new Date(start).toISOString(), end: new Date(start + len).toISOString(), meet }, 200, cors);
  } catch (e) {
    console.log("book error:", String(e && e.message || e));
    return json({ error: "failed", bookingUrl: env.BOOKING_URL || "" }, 502, cors);
  }
}

// one-time connection: the owner signs in with Google and allows calendar access
function page(title, text, status = 200) {
  const esc = (x) => String(x).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  return new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${esc(title)}</title>
<body style="font-family:system-ui;max-width:560px;margin:60px auto;padding:0 20px;line-height:1.5"><h1 style="font-size:22px">${esc(title)}</h1><p>${esc(text)}</p></body>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

async function gcalConnect(request, env) {
  const self = new URL(request.url).origin;
  if (!env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET) return page("Calendar not set up yet", "Add GOOGLE_CLIENT_ID and the GOOGLE_CLIENT_SECRET secret in Cloudflare first.", 400);
  if (!env.STATE) return page("Calendar not set up yet", "Add the KV binding named STATE in Cloudflare first.", 400);
  const state = crypto.randomUUID();
  await env.STATE.put(`gcal_state:${state}`, "1", { expirationTtl: 600 });
  const u = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  u.search = new URLSearchParams({ client_id: env.GOOGLE_CLIENT_ID, redirect_uri: `${self}/gcal/callback`, response_type: "code",
    scope: GCAL_SCOPES, access_type: "offline", prompt: "consent", include_granted_scopes: "true", state }).toString();
  return Response.redirect(u.toString(), 302);
}

async function gcalCallback(request, env) {
  const url = new URL(request.url), self = url.origin;
  const code = url.searchParams.get("code"), state = url.searchParams.get("state") || "";
  if (url.searchParams.get("error")) return page("Calendar not connected", "Google sign-in was cancelled or refused.", 400);
  if (!code || !env.STATE || !(await env.STATE.get(`gcal_state:${state}`))) return page("Calendar not connected", "This sign-in link has expired. Open /gcal/connect again.", 400);
  await env.STATE.delete(`gcal_state:${state}`);
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", code, redirect_uri: `${self}/gcal/callback`, client_id: env.GOOGLE_CLIENT_ID, client_secret: env.GOOGLE_CLIENT_SECRET }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.refresh_token) return page("Calendar not connected", `Google did not return a long-term key (${d.error || r.status}). Open /gcal/connect again and allow all requested access.`, 400);
  let email = "";
  try { email = JSON.parse(atob(String(d.id_token || "").split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).email || ""; } catch { email = ""; }
  const owner = String(env.CAL_OWNER || env.NOTIFY_CC || "").trim().toLowerCase();
  if (!owner || email.toLowerCase() !== owner) return page("Calendar not connected", "Only the website owner's Google account can be connected here.", 403);
  await env.STATE.put("gcal_refresh", d.refresh_token);
  tokenCache = { token: "", until: 0 };
  return page("Calendar connected", "The website agents can now show your free times and book calls into your Google Calendar. You can close this page.");
}

/* ---------------------------------------------------------------- entry points */

const SELF_URL = "https://mindfreedom-assistant.innoptesha.workers.dev/";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const allowed = ALLOWED_ORIGINS.includes(origin);
    const cors = corsFor(allowed ? origin : ALLOWED_ORIGINS[0]);
    const cfg = aiConfig(env);

    if (request.method === "GET" && url.pathname === "/gcal/connect") return gcalConnect(request, env);
    if (request.method === "GET" && url.pathname === "/gcal/callback") return gcalCallback(request, env);
    if (request.method === "GET") return json({
      ok: true, keySet: Boolean(cfg.key), provider: cfg.provider,
      agents: { chat: true, leads: true, bookingLink: Boolean(env.BOOKING_URL), emailSet: Boolean(env.NOTIFY_EMAIL), mailer: Boolean(env.MAILER),
        enquiries: true, watchdog: true, adsReport: Boolean(env.META_TOKEN), watchdogMemory: Boolean(env.STATE), calendar: await calendarReady(env) },
    }, 200, cors);
    if (request.method === "OPTIONS") return new Response(null, { status: allowed ? 204 : 403, headers: cors });
    if (request.method !== "POST") return json({ error: "not found" }, 404, cors);
    if (!allowed) return json({ error: "forbidden" }, 403, cors);

    if (url.pathname === "/enquiry") return handleEnquiry(request, env, ctx, cors);
    if (url.pathname === "/slots") return handleSlots(env, cors);
    if (url.pathname === "/book") return handleBook(request, env, ctx, cors);
    return handleChat(request, env, ctx, cors);
  },

  // Cron triggers: "17 */3 * * *" watchdog, "2 14 * * *" ads report (17:02 EAT)
  async scheduled(event, env, ctx) {
    if (/^\S+ 14 /.test(event.cron)) ctx.waitUntil(runAdsReport(env));
    else ctx.waitUntil(runWatchdog(env, env.SELF_URL || SELF_URL));
  },
};

