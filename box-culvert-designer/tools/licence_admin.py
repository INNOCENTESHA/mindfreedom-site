"""
Vendor tool for CBC Designer licences (keep the private key secret - never ship it, never commit it).

    python tools/licence_admin.py keypair                         # make a new signing keypair
    python tools/licence_admin.py issue  PRIV "Licensee name" 183 [--machine ID] [--order NO]
    python tools/licence_admin.py sign-manifest PRIV              # sign the integrity manifest over the program
    python tools/licence_admin.py public PRIV                     # print the public key to embed in licensing.py

PRIV is the private key string, or a path to a file holding it.
"""
import sys, os, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import licensing as L


def _priv(a):
    return open(a, encoding="utf-8").read().strip() if os.path.exists(a) else a


def main(argv):
    if not argv or argv[0] in ("-h", "--help"): print(__doc__); return
    cmd = argv[0]
    if cmd == "keypair":
        priv, pub = L.make_keypair()
        print("PRIVATE KEY (keep secret, never commit or ship):\n" + priv + "\n")
        print("PUBLIC KEY (paste into licensing.PUBLIC_KEY_B64):\n" + pub)
    elif cmd == "public":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(_priv(argv[1])))
        print(base64.b64encode(sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
    elif cmd == "issue":
        priv, name, days = _priv(argv[1]), argv[2], int(argv[3])
        machine = argv[argv.index("--machine") + 1] if "--machine" in argv else None
        order = argv[argv.index("--order") + 1] if "--order" in argv else ""
        print(L.issue_licence(priv, name, days, machine=machine, order=order))
    elif cmd == "sign-manifest":
        root = os.path.join(os.path.dirname(__file__), "..")
        print(L.sign_manifest(_priv(argv[1]), root))
    else:
        print("unknown command:", cmd); print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
