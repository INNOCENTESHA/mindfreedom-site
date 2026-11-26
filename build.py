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
webp = str(Path(icon).with_suffix(".webp")) if icon else ""
if icon and (ROOT / webp).is_file():   # smaller WebP copy beside the PNG, used where the browser supports it
    icon_html = (f'<picture><source srcset="{html.escape(webp)}" type="image/webp">'
                 f'<img src="{html.escape(icon)}" alt="" width="52" height="52"></picture>')
else:
    icon_html = f'<img src="{html.escape(icon)}" alt="" width="52" height="52">' if icon else ""
page = page.replace("{{WA_ICON}}", icon_html or GENERIC)
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
    "siteUrl": site["site"]["url"].rstrip("/"),
    "en": en,
}
cfg = json.dumps(config, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

# early language pick in <head>: language codes, plus browser languages the site does not have,
# mapped to the closest one it does (Kazakh, Tajik, Turkmen -> Russian, Azerbaijani -> Turkish, ...)
aliases = {"tl": "fil", "kk": "ru", "tg": "ru", "tk": "ru", "az": "tr", "ms": "id"}
aliases.update(site.get("languageAliases", {}))
codes = [l["code"] for l in langs]
for a, t in aliases.items():
    if t not in codes:
        sys.exit(f"languageAliases: {a} -> {t}, but {t} is not in languages")
page = page.replace("{{LANG_CODES}}", json.dumps(codes)).replace("{{LANG_ALIASES}}", json.dumps(aliases))
page = page.replace("{{I18N_PATH}}", config["i18nPath"])

# one address per language (?lang=xx) for search engines: <link hreflang> tags and sitemap.xml
SITE = site["site"]["url"].rstrip("/")
def lang_url(c):
    return f"{SITE}/" if c == "en" else f"{SITE}/?lang={c}"
alts = [f'<link rel="alternate" hreflang="{c}" href="{lang_url(c)}">' for c in codes]
alts.append(f'<link rel="alternate" hreflang="x-default" href="{SITE}/">')
page = page.replace("{{HREFLANG}}", "\n".join(alts)).replace("{{SITE_URL}}", SITE)
from datetime import date
xl = "".join(f'<xhtml:link rel="alternate" hreflang="{c}" href="{html.escape(lang_url(c))}"/>' for c in codes)
urls = "".join(f"<url><loc>{html.escape(lang_url(c))}</loc><lastmod>{date.today().isoformat()}</lastmod>{xl}</url>" for c in codes)
(ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
    + urls + "</urlset>\n", encoding="utf-8")

page = page.replace("{{CSS}}", read("src/site.css")).replace("{{CONFIG}}", cfg).replace("{{JS}}", read("src/site.js"))
left = re.findall(r"\{\{\w+\}\}", page)
if left:
    sys.exit(f"Unfilled placeholders: {left}")
(ROOT / "index.html").write_text(page, encoding="utf-8")
print(f"index.html built: {len(page.encode())/1024:.1f} KB, {len(langs)} languages, {len(en)} strings each")
