# CBC Designer — hand-off status and checklist

This records what is finished and what still needs **you** (your Windows PC, AutoCAD, a private repository, and a
second engineer). The software items I could finish here are done and tested; the rest cannot be completed from a
cloud Linux session.

## Done and tested in this session

| Item | Evidence |
|---|---|
| App writes its own complete `CBC_EXPORT.txt`; full AutoCAD sheet set from the app's own design | `export_writer.py`, `tests/test_export.py` (derived keys match the reference to the mm; generator runs, 9+ sheets) |
| Wing walls, aprons, cut-off walls designed to EN 1992 + EN 1997, scheduled, checked | `detailing/retaining.py`, `tests/test_retaining.py` (stability auto-sized; 10 tests) |
| Bars within manufacturing limits; over-length bars lapped; lap position rule (top at mid-span, bottom at supports) | `detailing/bars.py`, `tests/test_bars_skew.py` |
| Skew with the road horizontal | `detailing/skew.py`, `tests/skew_simulation.py` |
| Licence gate (Ed25519, dependency-free verify) + tamper manifest | `licensing.py`, `tools/licence_admin.py`, `tests/test_licensing.py` (8 tests) |
| Licence agreement (template) and protection guide | `LICENSE_AGREEMENT.md`, `PROTECTION.md` |
| **127 automated tests pass; 246-culvert what-if sweep: 0 crashes, 0 invariant violations** | `python -m pytest tests`; `python tests/scenarios.py` |

## You must do these — they cannot be done from here

1. **Run it on your Windows PC.** Double-click `CBC_Designer.bat`. First run installs the libraries. This is the
   biggest untested thing: the app has only ever run on Linux here. Report anything that breaks.

2. **Open a generated DXF in real AutoCAD.** Export the drawing set and confirm it reads correctly (layers, text,
   dimensions, tables). The DXF passes the `ezdxf` audit here but has not been opened in AutoCAD itself.

3. **Move the code to a private repository.** It is still in your **public** `mindfreedom-site` repo, which is wrong
   for a product you will sell. Create a private repo and I will move it, or copy the `box-culvert-designer` folder
   into it yourself. The private signing key and `licence.cbclic` are **not** in git (git-ignored) — keep them safe.

4. **Set up your own signing keys.** I generated a working keypair and a sample licence for you (delivered as files).
   For production, run `python tools/licence_admin.py keypair`, paste the new public key into
   `licensing.PUBLIC_KEY_B64`, keep the private key offline, and re-sign the manifest. See `PROTECTION.md`.

5. **Have a second engineer check real designs.** Before any output is issued for construction, an independent
   qualified engineer must verify the analysis, design and drawings — as the licence agreement itself requires.

## Known gaps (software, honest list)

- The reinforcement **section drawing** and the AutoCAD sheets still show the **square** section at a skew (the plan,
  wall lengths, counts and schedule are skew-aware; the cross-section is not yet re-drawn skewed).
- A full in-AutoCAD visual check of tables and leaders has not been done.
- The wing-wall **base** is sized for sliding without a shear key, so bases can be wide; add a key if you prefer.
- A few sweep cases still flag a lap that will not fit a short wall or a bar that fails a supply limit — the app
  flags them rather than auto-resizing.
- No MIDAS `.mct` export yet.

## Files you were sent separately (keep private)

- `licence.cbclic` — your working licence (183 days). Put it next to the program.
- `cbc_private_key.txt` — your **secret** signing key. Never commit, never ship, never email. Back it up offline.
- `cbc_public_key.txt` — the public key embedded in the app (not secret).
