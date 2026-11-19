# Protecting CBC Designer from copying and reverse engineering

This explains what the software does to resist copying and reverse engineering, how to operate it, and — just as
important — the honest limits of that protection. Read all of it before you rely on any of it.

## The blunt truth first

**Software that runs on someone else's computer can always, in principle, be reverse engineered.** The machine has to
be able to execute it, so the instructions are present and can be read with enough effort. This is true of every
program, including ones compiled from C++. It is *especially* true of Python, whose byte-code decompiles close to the
original source. Tools exist (including automated reverse-engineering agents) that do this quickly.

So the goal is **not** an unbreakable wall. The goal is to raise the cost and the legal risk of copying high enough
that paying your fee is the easier choice for an honest customer, and that a dishonest one is clearly in breach. The
protection is three things working together, in order of real strength:

1. **The licence agreement (legal).** `LICENSE_AGREEMENT.md` forbids reverse engineering, sharing and redistribution,
   and ties each user to a paid half-year term. This is your strongest protection, because it works even after the
   code has been read.
2. **Keeping the signing key secret (operational).** Only you can issue licences, because only you hold the private
   key. Guard it.
3. **Technical measures (this file).** They deter casual copying and tampering. A determined expert gets past them.

## What is built in

### 1. Licence check (`licensing.py`)

- A licence is a signed statement — licensee, expiry (183 days by default), features — that **only you can issue**,
  because it is signed with your **Ed25519 private key**. The program carries only the matching **public key** and
  verifies the signature. Nobody can forge or extend a licence without the private key.
- Verification uses a self-contained Ed25519 implementation, so the shipped program needs no cryptography library.
- Without a valid, unexpired licence the program runs in **evaluation mode**: analysis and design work so a buyer can
  try it, but **drawing/DXF/PDF export is disabled** and outputs are marked. Replace or extend that policy to taste.
- A licence can be **bound to one computer** with `--machine`: pass the customer's `machine_id()` so the licence only
  runs there.

### 2. Integrity / tamper check (`manifest.cbcsig`)

- `manifest.cbcsig` lists a SHA-256 of every program file, and is itself signed with your private key. At start-up the
  program recomputes the hashes and warns if any file was **changed, added or removed**. This resists casual patching
  of the licence check, because patching a file changes its hash, and the attacker cannot re-sign the manifest.
- Regenerate it on every build: `python tools/licence_admin.py sign-manifest PRIVATE_KEY > manifest.cbcsig`.

### 3. Ship compiled, not source

- `build_exe.bat` builds a single `CBC_Designer.exe` with PyInstaller. Ship that, **not** the `.py` files. It bundles
  Python byte-code, which is far less convenient to read than source and needs no Python on the customer's machine.

## How to operate it (vendor workflow)

1. **Make your own keypair once** and keep the private key offline (a password manager, an encrypted USB — never in the
   repository, never on a customer machine, never in an email):

   ```
   python tools/licence_admin.py keypair
   ```

   Paste the printed **public** key into `licensing.PUBLIC_KEY_B64`. Keep the **private** key secret.

2. **Issue a licence** for each paying customer (183 days = one half-year):

   ```
   python tools/licence_admin.py issue  PRIVATE_KEY  "Customer Name"  183  --order INV-1234
   # optionally lock to one computer:  --machine <their machine_id>
   ```

   Send them the printed text as `licence.cbclic`, to sit next to the program (or point `CBC_LICENCE` at it).

3. **Sign the build** just before you ship it:

   ```
   python tools/licence_admin.py sign-manifest PRIVATE_KEY > manifest.cbcsig
   ```

4. **Build the executable** and distribute only `dist\CBC_Designer\` plus the customer's `licence.cbclic`:

   ```
   build_exe.bat
   ```

## How to make it genuinely harder (optional, recommended for sale)

The built-in measures stop casual copying. To raise the cost against a skilled reverse-engineer:

- **Obfuscate the byte-code** with a commercial tool such as **PyArmor** before PyInstaller. This encrypts the
  byte-code and binds it to a licence of its own. It is the single biggest practical improvement for a Python product.
  (`pip install pyarmor`; `pyarmor gen --pack onefile app.py`.) It is not installed here — add it on your build machine.
- **Move the crown jewels off the device.** The strongest protection is to *not ship* your most valuable logic at all:
  run the analysis/design engine on a server you control and have the desktop app call it with the licence. Then the
  customer never has the code to reverse engineer. This is more work but it is the only approach that defeats a
  determined expert.
- **Sign the executable** with a code-signing certificate so Windows shows your name and tampering is visible.
- **Rotate keys** and keep terms short (the half-year term already helps: a cracked copy stops working at expiry).

## What will NOT protect you, and don't rely on

- Hiding the licence check deep in the code — it can be found and patched.
- A symmetric secret embedded in the app — if the app can check it, an attacker can read it. (This is why licences are
  **asymmetrically** signed: the app holds only the public key.)
- Byte-code alone — it decompiles.

## If you suspect a copy is in circulation

Your remedy is legal, under the licence agreement, plus key rotation (issue a new build with a new public key, and new
licences, so old cracked copies and leaked licences stop verifying).
