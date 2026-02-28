from __future__ import annotations

import json
import time
from pathlib import Path

from .errors import AdapterExecutionError


class VendorCertPinset:
    def __init__(self, pinset_path: str) -> None:
        self.pinset_path = Path(pinset_path)
        self._data = self._load()

    def _load(self) -> dict[str, object]:
        if not self.pinset_path.exists():
            return {"vendors": {}}
        return json.loads(self.pinset_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.pinset_path.parent.mkdir(parents=True, exist_ok=True)
        self.pinset_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def assert_vendor_fingerprint_allowed(self, vendor_id: str, fingerprint: str) -> None:
        vendors = self._data.get("vendors", {})
        vendor = vendors.get(vendor_id)
        if not isinstance(vendor, dict):
            raise AdapterExecutionError(f"unknown vendor id for cert attestation: {vendor_id}")

        revoked = set(vendor.get("revoked", []))
        if fingerprint in revoked:
            raise AdapterExecutionError("revoked vendor certificate fingerprint")

        now = time.time()
        self._auto_cutover(vendor)
        allowed = self._collect_allowed_fingerprints(vendor, now)
        if fingerprint not in allowed:
            raise AdapterExecutionError("certificate fingerprint not pinned for vendor")

    def _collect_allowed_fingerprints(self, vendor: dict[str, object], now: float) -> set[str]:
        active = vendor.get("active", [])
        next_pins = vendor.get("next", [])

        if isinstance(active, list) or isinstance(next_pins, list):
            allowed: set[str] = set()
            for pin in active if isinstance(active, list) else []:
                fingerprint = self._valid_pin_fingerprint(pin, now)
                if fingerprint:
                    allowed.add(fingerprint)
            for pin in next_pins if isinstance(next_pins, list) else []:
                fingerprint = self._valid_pin_fingerprint(pin, now)
                if fingerprint:
                    allowed.add(fingerprint)
            if allowed:
                return allowed

        return set(vendor.get("allowed", []))

    def _valid_pin_fingerprint(self, pin: object, now: float) -> str | None:
        if not isinstance(pin, dict):
            return None
        fingerprint_raw = pin.get("fingerprint")
        if not isinstance(fingerprint_raw, str):
            return None

        not_before = pin.get("not_before")
        not_after = pin.get("not_after")

        if not_before is not None and float(not_before) > now:
            return None
        if not_after is not None and float(not_after) < now:
            return None
        return fingerprint_raw

    def _auto_cutover(self, vendor: dict[str, object]) -> None:
        active = vendor.get("active", [])
        next_pins = vendor.get("next", [])
        if not isinstance(active, list) or not isinstance(next_pins, list):
            return

        now = time.time()
        active_original = list(active)
        active_valid = [pin for pin in active if self._valid_pin_fingerprint(pin, now)]
        next_valid = [pin for pin in next_pins if self._valid_pin_fingerprint(pin, now)]

        changed = False
        if len(active_valid) != len(active):
            vendor["active"] = active_valid
            changed = True

        if not active_valid and next_valid:
            previous_active = vendor.get("previous_active", [])
            if not isinstance(previous_active, list):
                previous_active = []
            if active_original:
                previous_active = active_original
            vendor["previous_active"] = previous_active
            vendor["active"] = next_valid
            vendor["next"] = [pin for pin in next_pins if pin not in next_valid]
            changed = True

        if changed:
            self._save()

    def rotate_vendor_pin(self, vendor_id: str, fingerprint: str) -> None:
        vendors = self._data.setdefault("vendors", {})
        vendor = vendors.setdefault(vendor_id, {"allowed": [], "active": [], "next": [], "revoked": []})
        allowed = vendor.setdefault("allowed", [])
        if fingerprint not in allowed:
            allowed.append(fingerprint)

        active = vendor.setdefault("active", [])
        if not any(isinstance(pin, dict) and pin.get("fingerprint") == fingerprint for pin in active):
            active.append({"fingerprint": fingerprint, "not_before": None, "not_after": None})
        self._save()

    def schedule_next_pin(
        self,
        vendor_id: str,
        fingerprint: str,
        activate_at: float,
        expires_at: float | None = None,
    ) -> None:
        vendors = self._data.setdefault("vendors", {})
        vendor = vendors.setdefault(vendor_id, {"allowed": [], "active": [], "next": [], "revoked": []})
        next_pins = vendor.setdefault("next", [])
        if not any(isinstance(pin, dict) and pin.get("fingerprint") == fingerprint for pin in next_pins):
            next_pins.append(
                {
                    "fingerprint": fingerprint,
                    "not_before": activate_at,
                    "not_after": expires_at,
                }
            )
        self._save()

    def rollback_to_previous_active(self, vendor_id: str) -> None:
        vendors = self._data.get("vendors", {})
        vendor = vendors.get(vendor_id)
        if not isinstance(vendor, dict):
            raise AdapterExecutionError(f"unknown vendor id for cert attestation: {vendor_id}")

        previous_active = vendor.get("previous_active", [])
        if not isinstance(previous_active, list) or not previous_active:
            raise AdapterExecutionError("no previous active pinset available for rollback")

        current_active = vendor.get("active", [])
        if not isinstance(current_active, list):
            current_active = []

        next_pins = vendor.get("next", [])
        if not isinstance(next_pins, list):
            next_pins = []

        vendor["next"] = current_active + next_pins
        vendor["active"] = previous_active
        vendor["previous_active"] = []
        self._save()

    def revoke_vendor_pin(self, vendor_id: str, fingerprint: str) -> None:
        vendors = self._data.setdefault("vendors", {})
        vendor = vendors.setdefault(vendor_id, {"allowed": [], "active": [], "next": [], "revoked": []})
        revoked = vendor.setdefault("revoked", [])
        if fingerprint not in revoked:
            revoked.append(fingerprint)
        self._save()
