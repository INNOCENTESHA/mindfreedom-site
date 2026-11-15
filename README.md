# mindfreedom.co.tz

Website of Mind Freedom AI Consultancy. Hosted on GitHub Pages from the `main` branch.

## How it is organised

| Path | What it holds |
|---|---|
| `content/site.json` | Settings: list of languages, WhatsApp number and icon file, optional assistant endpoint |
| `content/i18n/<code>.json` | The text of the site, one file per language (20 languages, same keys in each) |
| `src/template.html` | Page structure. Translated elements carry `data-i18n="key"` |
| `src/widgets.html` | WhatsApp button and assistant panel |
| `src/site.css`, `src/site.js` | Styles and behaviour |
| `build.py` | Python build script (standard library only) that writes `index.html` |
| `index.html` | Built page. Do not edit by hand; edit the sources and rebuild |
| `worker/assistant-worker.js` | Optional server-side upgrade for the assistant (not deployed) |

## Changing something

1. Edit the JSON or `src/` file.
2. Run `python3 build.py`. It stops with a message if a language is missing a key.
3. Commit and push; GitHub Pages publishes within a minute or two.

**Change a sentence:** edit the key in `content/i18n/en.json` and in the other language files.
**Add a language:** copy `en.json` to `<code>.json`, translate the values, add one line to
`languages` in `content/site.json` (`"dir": "rtl"` for right-to-left scripts), rebuild.

**WhatsApp icon:** the icon file is `assets/whatsapp.png`, named by `"whatsappIcon"` in `content/site.json`, rebuild.

Product names (QGIS, MIDAS Civil, AutoCAD and so on) are not translated.
