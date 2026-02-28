from __future__ import annotations

import json
from pathlib import Path

from .errors import AdapterExecutionError


class VendorAckKeyring:
    def __init__(self, keyring_path: str) -> None:
        self.keyring_path = Path(keyring_path)
        self._data = self._load()

    def _load(self) -> dict[str, object]:
        if not self.keyring_path.exists():
            return {"vendors": {}}
        return json.loads(self.keyring_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.keyring_path.parent.mkdir(parents=True, exist_ok=True)
        self.keyring_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get_key_descriptor(self, vendor_id: str, key_id: str) -> dict[str, str]:
        vendors = self._data.get("vendors", {})
        vendor = vendors.get(vendor_id)
        if not isinstance(vendor, dict):
            raise AdapterExecutionError(f"unknown vendor id: {vendor_id}")

        revoked = set(vendor.get("revoked", []))
        if key_id in revoked:
            raise AdapterExecutionError(f"revoked ack key id: {key_id}")

        keys = vendor.get("keys", {})
        entry = keys.get(key_id) if isinstance(keys, dict) else None
        if not isinstance(entry, dict):
            raise AdapterExecutionError(f"unknown ack key id: {key_id}")
        algorithm = entry.get("algorithm")
        public_key_b64 = entry.get("public_key_b64")
        if not isinstance(algorithm, str) or not isinstance(public_key_b64, str):
            raise AdapterExecutionError(f"invalid key descriptor for key id: {key_id}")
        return {
            "algorithm": algorithm,
            "public_key_b64": public_key_b64,
        }

    def rotate_vendor_key(self, vendor_id: str, key_id: str, algorithm: str, public_key_b64: str) -> None:
        vendors = self._data.setdefault("vendors", {})
        vendor = vendors.setdefault(vendor_id, {"active_kid": key_id, "keys": {}, "revoked": []})
        keys = vendor.setdefault("keys", {})
        keys[key_id] = {
            "algorithm": algorithm,
            "public_key_b64": public_key_b64,
        }
        vendor["active_kid"] = key_id
        self._save()

    def revoke_vendor_key(self, vendor_id: str, key_id: str) -> None:
        vendors = self._data.setdefault("vendors", {})
        vendor = vendors.setdefault(vendor_id, {"active_kid": "", "keys": {}, "revoked": []})
        revoked = vendor.setdefault("revoked", [])
        if key_id not in revoked:
            revoked.append(key_id)
        if vendor.get("active_kid") == key_id:
            vendor["active_kid"] = ""
        self._save()
