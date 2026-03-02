from __future__ import annotations

import argparse
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


DEFAULT_PRIVATE_KEY_B64 = "Pm/gBY5fOOUUOnIwxHP4mynthIjuMwzyCpXqfA/l+fk="


class MockVendorState:
    def __init__(self, private_key_b64: str) -> None:
        self.vendor_id = "mock-vendor"
        self.key_id = "mock-k1"
        self.fingerprint = "sha256:mock-fingerprint"
        self.required_token = "mock-token"
        self.private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64, validate=True))
        self._nonce = 1000
        self._lock = threading.Lock()

    def next_nonce(self) -> int:
        with self._lock:
            self._nonce += 1
            return self._nonce


def _sign_ack(private_key: Ed25519PrivateKey, ack_payload: dict[str, object]) -> str:
    canonical = json.dumps(ack_payload, sort_keys=True, separators=(",", ":"))
    signature = private_key.sign(canonical.encode("utf-8"))
    return base64.b64encode(signature).decode("utf-8")


class MockVendorHandler(BaseHTTPRequestHandler):
    state: MockVendorState

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/vehicles/") or not self.path.endswith("/commands"):
            self._json(404, {"detail": "Not Found"})
            return

        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.state.required_token}"
        if auth != expected:
            self._json(401, {"detail": "Unauthorized"})
            return

        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError:
            self._json(400, {"detail": "invalid content length"})
            return

        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"detail": "invalid json"})
            return

        command_id = payload.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            self._json(400, {"detail": "missing command_id"})
            return

        ack: dict[str, object] = {
            "command_id": command_id,
            "ack_nonce": self.state.next_nonce(),
            "vendor_id": self.state.vendor_id,
            "ack_kid": self.state.key_id,
            "mtls_cert_fingerprint": self.state.fingerprint,
        }
        ack["ack_signature"] = _sign_ack(self.state.private_key, ack)
        self._json(200, ack)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock vendor command gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--private-key-b64", default=DEFAULT_PRIVATE_KEY_B64)
    args = parser.parse_args()

    state = MockVendorState(private_key_b64=args.private_key_b64)
    MockVendorHandler.state = state

    server = ThreadingHTTPServer((args.host, args.port), MockVendorHandler)
    print(f"mock gateway listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
