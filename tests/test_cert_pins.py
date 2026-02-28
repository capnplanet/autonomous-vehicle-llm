import time

from autonomy.cert_pins import VendorCertPinset
from autonomy.errors import AdapterExecutionError


def test_pinset_rotate_and_assert(tmp_path):
    pinset_path = tmp_path / "pins.json"
    pinset = VendorCertPinset(str(pinset_path))

    pinset.rotate_vendor_pin("vendor-a", "sha256:abc")
    pinset.assert_vendor_fingerprint_allowed("vendor-a", "sha256:abc")


def test_pinset_revocation_blocks_fingerprint(tmp_path):
    pinset_path = tmp_path / "pins.json"
    pinset = VendorCertPinset(str(pinset_path))

    pinset.rotate_vendor_pin("vendor-a", "sha256:abc")
    pinset.revoke_vendor_pin("vendor-a", "sha256:abc")

    try:
        pinset.assert_vendor_fingerprint_allowed("vendor-a", "sha256:abc")
        assert False, "expected AdapterExecutionError"
    except AdapterExecutionError as exc:
        assert "revoked vendor certificate fingerprint" in str(exc)


def test_pinset_auto_cutover_to_next_window(tmp_path):
    pinset_path = tmp_path / "pins.json"
    pinset = VendorCertPinset(str(pinset_path))

    now = time.time()
    pinset.rotate_vendor_pin("vendor-a", "sha256:old")
    pinset.schedule_next_pin(
        vendor_id="vendor-a",
        fingerprint="sha256:new",
        activate_at=now - 5,
        expires_at=now + 100,
    )

    data = pinset._data
    data["vendors"]["vendor-a"]["active"] = [
        {"fingerprint": "sha256:old", "not_before": now - 100, "not_after": now - 10}
    ]
    pinset._save()

    pinset.assert_vendor_fingerprint_allowed("vendor-a", "sha256:new")


def test_pinset_rollback_to_previous_active(tmp_path):
    pinset_path = tmp_path / "pins.json"
    pinset = VendorCertPinset(str(pinset_path))

    now = time.time()
    pinset._data = {
        "vendors": {
            "vendor-a": {
                "active": [{"fingerprint": "sha256:new", "not_before": now - 10, "not_after": now + 10}],
                "next": [],
                "previous_active": [
                    {"fingerprint": "sha256:old", "not_before": None, "not_after": None}
                ],
                "allowed": ["sha256:old", "sha256:new"],
                "revoked": [],
            }
        }
    }
    pinset._save()

    pinset.rollback_to_previous_active("vendor-a")

    pinset.assert_vendor_fingerprint_allowed("vendor-a", "sha256:old")
