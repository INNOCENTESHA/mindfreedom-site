"""Licence signing/verification and the integrity manifest."""
import os, sys, json, base64, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
import licensing as L

cryptography = pytest.importorskip("cryptography")


@pytest.fixture(scope="module")
def keys():
    return L.make_keypair()


def test_valid_licence_verifies(keys):
    priv, pub = keys
    lic = L.issue_licence(priv, "Acme Engineers", days=183, order="INV-1")
    claims = L.verify_licence(lic, public_b64=pub)
    assert claims["licensee"] == "Acme Engineers" and 180 < L.days_left(claims) <= 183


def test_forged_signature_is_rejected(keys):
    priv, pub = keys
    lic = json.loads(L.issue_licence(priv, "x", days=10))
    sig = bytearray(base64.b64decode(lic["signature"])); sig[0] ^= 1
    lic["signature"] = base64.b64encode(bytes(sig)).decode()
    with pytest.raises(L.LicenceError): L.verify_licence(json.dumps(lic), public_b64=pub)


def test_tampered_claim_is_rejected(keys):
    priv, pub = keys
    lic = json.loads(L.issue_licence(priv, "x", days=10))
    lic["licensee"] = "someone else"                      # change a signed field
    with pytest.raises(L.LicenceError): L.verify_licence(json.dumps(lic), public_b64=pub)


def test_wrong_key_is_rejected(keys):
    priv, _pub = keys
    _priv2, pub2 = L.make_keypair()
    lic = L.issue_licence(priv, "x", days=10)
    with pytest.raises(L.LicenceError): L.verify_licence(lic, public_b64=pub2)


def test_expired_is_rejected(keys):
    priv, pub = keys
    with pytest.raises(L.LicenceError): L.verify_licence(L.issue_licence(priv, "x", days=-1), public_b64=pub)


def test_machine_binding(keys):
    priv, pub = keys
    lic = L.issue_licence(priv, "x", days=10, machine="AAAA")
    assert L.verify_licence(lic, public_b64=pub)["machine"] == "AAAA"
    assert len(L.machine_id()) == 24


def test_manifest_detects_tampering(keys, tmp_path):
    priv, pub = keys
    root = str(tmp_path)
    open(os.path.join(root, "a.py"), "w").write("print(1)\n")
    open(os.path.join(root, "b.py"), "w").write("x = 2\n")
    man = L.sign_manifest(priv, root)
    assert L.verify_manifest(root, man, public_b64=pub) == []       # intact
    open(os.path.join(root, "a.py"), "a").write("# patched\n")      # tamper
    bad = L.verify_manifest(root, man, public_b64=pub)
    assert any("changed: a.py" in x for x in bad)
    open(os.path.join(root, "c.py"), "w").write("y=3\n")            # added file
    assert any("added: c.py" in x for x in L.verify_manifest(root, man, public_b64=pub))


def test_embedded_public_key_is_real():
    assert L.PUBLIC_KEY_B64 != "PLACEHOLDER_PUBLIC_KEY" and len(base64.b64decode(L.PUBLIC_KEY_B64)) == 32
