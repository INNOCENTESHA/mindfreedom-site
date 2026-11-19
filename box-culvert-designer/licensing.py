"""
Licensing and integrity for CBC Designer.

A licence is a signed statement - licensee, expiry, features, and optionally a machine fingerprint - that only
the vendor can issue, because only the vendor holds the private signing key.  The application carries the matching
public key and verifies the signature at start-up; it cannot create or alter a licence.

The verifier is a self-contained Ed25519 implementation (RFC 8032), so the shipped application needs no
cryptography library.  Signing (vendor side only) uses the `cryptography` package - see `issue_licence`.

    verify_licence(text) -> dict            # the licence claims, or raises LicenceError
    check(path=None, require_machine=False) # the start-up gate: returns the licence or raises
    machine_id()                            # a stable fingerprint of this computer
    issue_licence(priv, licensee, days, ..) # VENDOR ONLY: make a signed licence
    sign_manifest / verify_manifest         # tamper check over the program files

HONEST LIMITS.  This raises the cost of copying and of running past the term, and it ties a build to its files.
It is not unbreakable: a determined person who can run a Python debugger can patch the check out of a source or
byte-code build.  The real protection is (1) keeping the private key secret, (2) shipping a compiled build, not
source, (3) the licence agreement.  See PROTECTION.md.
"""
from __future__ import annotations
import base64, hashlib, json, os, time, platform, uuid

# ----- the vendor's public key (base64 of 32 raw bytes).  Replace with your own from `make_keypair`.
PUBLIC_KEY_B64 = "LDJeaR9rfU6xWYmg5C7fqXRKV8oiq2658JoW2UAmmsE="


class LicenceError(Exception):
    pass


# --------------------------------------------------------------------------- Ed25519 verify (RFC 8032, pure python)
_p = 2 ** 255 - 19
_d = (-121665 * pow(121666, _p - 2, _p)) % _p
_I = pow(2, (_p - 1) // 4, _p)
_q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x): return pow(x, _p - 2, _p)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p != 0: x = (x * _I) % _p
    if x % 2 != 0: x = _p - x
    return x


_By = (4 * _inv(5)) % _p
_Bx = _xrecover(_By)
_B = (_Bx % _p, _By % _p, 1, (_Bx * _By) % _p)


def _edwards_add(P, Q):
    x1, y1, z1, t1 = P; x2, y2, z2, t2 = Q
    a = ((y1 - x1) * (y2 - x2)) % _p; b = ((y1 + x1) * (y2 + x2)) % _p
    c = (t1 * 2 * _d * t2) % _p; dd = (z1 * 2 * z2) % _p
    e = b - a; f = dd - c; g = dd + c; h = b + a
    return ((e * f) % _p, (g * h) % _p, (f * g) % _p, (e * h) % _p)


def _scalarmult(P, e):
    if e == 0: return (0, 1, 1, 0)
    Q = _scalarmult(P, e // 2); Q = _edwards_add(Q, Q)
    if e & 1: Q = _edwards_add(Q, P)
    return Q


def _encodepoint(P):
    x, y, z, _t = P; zi = _inv(z); x = (x * zi) % _p; y = (y * zi) % _p
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _bit(h, i): return (h[i // 8] >> (i % 8)) & 1


def _isoncurve(P):
    x, y, z, t = P
    return (z % _p != 0 and x * y % _p == z * t % _p and
            (y * y - x * x - z * z - _d * t * t) % _p == 0)


def _decodeint(s): return int.from_bytes(s, "little")


def _decodepoint(s):
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, 255): x = _p - x
    P = (x, y, 1, (x * y) % _p)
    if not _isoncurve(P): raise LicenceError("bad public key / signature point")
    return P


def ed25519_verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    if len(sig) != 64 or len(public) != 32: return False
    try:
        A = _decodepoint(public)
        R = _decodepoint(sig[:32])
        S = _decodeint(sig[32:])
    except Exception:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + public + msg).digest(), "little") % _q
    x1, y1, z1, _t1 = _scalarmult(_B, S)
    x2, y2, z2, _t2 = _edwards_add(R, _scalarmult(A, h))
    return (x1 * z2 - x2 * z1) % _p == 0 and (y1 * z2 - y2 * z1) % _p == 0


# --------------------------------------------------------------------------- licence
def _canonical(claims: dict) -> bytes:
    return json.dumps({k: claims[k] for k in sorted(claims) if k != "signature"}, separators=(",", ":"), sort_keys=True).encode()


def verify_licence(text: str, public_b64: str | None = None) -> dict:
    """Verify a licence string (JSON).  Returns its claims or raises LicenceError."""
    pk = base64.b64decode(public_b64 or PUBLIC_KEY_B64) if (public_b64 or PUBLIC_KEY_B64) != "PLACEHOLDER_PUBLIC_KEY" else None
    if pk is None: raise LicenceError("no public key built into this program")
    try:
        claims = json.loads(text)
        sig = base64.b64decode(claims["signature"])
    except Exception as ex:
        raise LicenceError(f"licence not readable: {ex}")
    if not ed25519_verify(pk, _canonical(claims), sig):
        raise LicenceError("licence signature is not valid (not issued by the vendor, or altered)")
    if claims.get("expiry") and time.time() > float(claims["expiry"]):
        raise LicenceError(f"licence expired on {time.strftime('%Y-%m-%d', time.gmtime(float(claims['expiry'])))}")
    return claims


def machine_id() -> str:
    """A stable fingerprint of this computer (MAC + host + platform).  Not secret; ties a licence to a machine."""
    raw = f"{uuid.getnode()}|{platform.node()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def licence_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.environ.get("CBC_LICENCE"), os.path.join(here, "licence.cbclic"),
            os.path.join(os.path.expanduser("~"), ".cbc", "licence.cbclic")]


def check(path: str | None = None, require_machine: bool = False) -> dict:
    """Start-up gate.  Finds and verifies a licence; raises LicenceError if none is valid."""
    for p in ([path] if path else licence_paths()):
        if p and os.path.exists(p):
            claims = verify_licence(open(p, encoding="utf-8").read())
            if require_machine and claims.get("machine") and claims["machine"] != machine_id():
                raise LicenceError("licence is for a different computer")
            return claims
    raise LicenceError("no licence file found (set CBC_LICENCE or place licence.cbclic next to the program)")


def days_left(claims: dict) -> float:
    return (float(claims["expiry"]) - time.time()) / 86400.0 if claims.get("expiry") else float("inf")


# --------------------------------------------------------------------------- integrity manifest (tamper check)
def _program_files(root: str):
    for dp, _dn, fn in os.walk(root):
        if any(part in dp for part in (os.sep + "_reference", os.sep + "tests", os.sep + "__pycache__", os.sep + ".git")): continue
        for f in sorted(fn):
            if f.endswith((".py", ".bat")) and f != "licence.cbclic":
                yield os.path.relpath(os.path.join(dp, f), root)


def build_manifest(root: str) -> dict:
    files = {}
    for rel in _program_files(root):
        files[rel] = hashlib.sha256(open(os.path.join(root, rel), "rb").read()).hexdigest()
    return {"files": files, "built": time.time()}


def verify_manifest(root: str, manifest_text: str, public_b64: str | None = None) -> list:
    """Return the list of changed / missing / added program files (empty = intact).  Signature-checked."""
    m = json.loads(manifest_text)
    if "signature" in m:
        pk = base64.b64decode(public_b64 or PUBLIC_KEY_B64)
        if not ed25519_verify(pk, _canonical(m), base64.b64decode(m["signature"])):
            raise LicenceError("manifest signature invalid")
    want = m["files"]; bad = []
    seen = set()
    for rel in _program_files(root):
        seen.add(rel); h = hashlib.sha256(open(os.path.join(root, rel), "rb").read()).hexdigest()
        if rel not in want: bad.append(f"added: {rel}")
        elif want[rel] != h: bad.append(f"changed: {rel}")
    for rel in want:
        if rel not in seen: bad.append(f"missing: {rel}")
    return bad


# --------------------------------------------------------------------------- vendor side (needs `cryptography`)
def make_keypair() -> tuple:
    """(private_b64, public_b64).  Keep the private key secret and off every shipped device."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    sk = Ed25519PrivateKey.generate()
    raw_priv = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    raw_pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw_priv).decode(), base64.b64encode(raw_pub).decode()


def _sign(priv_b64: str, payload: dict) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    return base64.b64encode(sk.sign(_canonical(payload))).decode()


def issue_licence(priv_b64: str, licensee: str, days: int = 183, features=("all",), machine: str | None = None, order: str = "") -> str:
    """VENDOR ONLY.  A signed licence valid for `days` (183 = half a year)."""
    claims = dict(licensee=licensee, issued=time.time(), expiry=time.time() + days * 86400,
                  features=list(features), order=order, product="CBC Designer")
    if machine: claims["machine"] = machine
    claims["signature"] = _sign(priv_b64, claims)
    return json.dumps(claims, indent=1)


def sign_manifest(priv_b64: str, root: str) -> str:
    m = build_manifest(root); m["signature"] = _sign(priv_b64, m)
    return json.dumps(m, indent=1)
