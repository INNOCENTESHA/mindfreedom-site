#!/usr/bin/env python3
"""Build index.html for mindfreedom.co.tz.

Sources
  content/site.json        settings: languages, WhatsApp number and icon, assistant endpoint
  content/i18n/<code>.json one file of text per language (all files must share the same keys)
  src/template.html        page structure; elements carry data-i18n="key"
  src/widgets.html         WhatsApp button and assistant panel
  src/site.css, src/site.js

Run:  python3 build.py      (standard library only)
The built index.html has English baked in, so search engines and visitors without
JavaScript get a complete page. Other languages load from content/i18n/ on demand.
"""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
read = lambda p: (ROOT / p).read_text(encoding="utf-8")

site = json.loads(read("content/site.json"))
langs = site["languages"]
texts = {l["code"]: json.loads(read(f"content/i18n/{l['code']}.json")) for l in langs}
en = texts["en"]

# every language must have exactly the English keys
bad = {c: sorted(set(t) ^ set(en)) for c, t in texts.items() if set(t) != set(en)}
if bad:
    sys.exit(f"Translation keys do not match en.json: {bad}")
for c, t in texts.items():
    if not re.fullmatch(r"[^<>]*<em>[^<>]+</em>[^<>]*", t["hero_h1"]):
        sys.exit(f"{c}: hero_h1 must contain exactly one <em>…</em> and no other markup")

page = read("src/template.html").replace("{{WIDGETS}}", read("src/widgets.html"))
page = page.replace("{{WA}}", site["site"]["whatsapp"])

# WhatsApp icon: the official icon file if one is supplied (site.whatsappIcon), else a plain chat glyph
GENERIC = ('<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
           '<path d="M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.7-5.1A8.5 8.5 0 1 1 21 12z"/></svg>')
icon = site["site"].get("whatsappIcon", "")
if icon and not (ROOT / icon).is_file():
    sys.exit(f"whatsappIcon file not found: {icon}")
page = page.replace("{{WA_ICON}}", f'<img src="{html.escape(icon)}" alt="" width="52" height="52">' if icon else GENERIC)
page = page.replace("{{WA_CLASS}}", " has-img" if icon else "")

def key(k):
    if k not in en:
        sys.exit(f"Template uses unknown key: {k}")
    return en[k]

# fill empty translated elements with English
page = re.sub(r'(data-i18n="(\w+)"[^>]*>)(?=</)', lambda m: m.group(1) + html.escape(key(m.group(2)), quote=False), page)
page = re.sub(r'(data-i18n-html="(\w+)"[^>]*>)(?=</)', lambda m: m.group(1) + key(m.group(2)), page)
page = re.sub(r'data-i18n-ph="(\w+)"', lambda m: f'{m.group(0)} placeholder="{html.escape(key(m.group(1)))}"', page)
page = re.sub(r'data-i18n-aria="(\w+)"', lambda m: f'{m.group(0)} aria-label="{html.escape(key(m.group(1)))}"', page)

config = {
    "langs": langs,
    "i18nPath": site.get("i18nPath", "content/i18n/"),
    "assistantEndpoint": site.get("assistantEndpoint", ""),
    "en": en,
}
cfg = json.dumps(config, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

page = page.replace("{{CSS}}", read("src/site.css")).replace("{{CONFIG}}", cfg).replace("{{JS}}", read("src/site.js"))
left = re.findall(r"\{\{\w+\}\}", page)
if left:
    sys.exit(f"Unfilled placeholders: {left}")
(ROOT / "index.html").write_text(page, encoding="utf-8")
print(f"index.html built: {len(page.encode())/1024:.1f} KB, {len(langs)} languages, {len(en)} strings each")
