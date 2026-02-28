from autonomy.errors import AdapterExecutionError
from autonomy.keyring import VendorAckKeyring


def test_keyring_rotation_and_lookup(tmp_path):
    keyring_path = tmp_path / "ack_keyring.json"
    keyring = VendorAckKeyring(str(keyring_path))

    keyring.rotate_vendor_key("vendor-a", "kid-1", "ed25519", "cHVibGljLWtleS0x")
    keyring.rotate_vendor_key("vendor-a", "kid-2", "ed25519", "cHVibGljLWtleS0y")

    first = keyring.get_key_descriptor("vendor-a", "kid-1")
    second = keyring.get_key_descriptor("vendor-a", "kid-2")
    assert first["algorithm"] == "ed25519"
    assert second["public_key_b64"] == "cHVibGljLWtleS0y"


def test_keyring_revocation_blocks_lookup(tmp_path):
    keyring_path = tmp_path / "ack_keyring.json"
    keyring = VendorAckKeyring(str(keyring_path))

    keyring.rotate_vendor_key("vendor-a", "kid-1", "ed25519", "cHVibGljLWtleQ==")
    keyring.revoke_vendor_key("vendor-a", "kid-1")

    try:
        keyring.get_key_descriptor("vendor-a", "kid-1")
        assert False, "expected AdapterExecutionError"
    except AdapterExecutionError as exc:
        assert "revoked ack key id" in str(exc)
