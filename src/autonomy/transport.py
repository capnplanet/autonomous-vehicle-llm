from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from urllib import error, request

from .errors import AdapterExecutionError
from .models import RetryPolicy, TransportConfig


class CommandTransport(ABC):
    @abstractmethod
    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        raise NotImplementedError


class HttpCommandTransport(CommandTransport):
    def __init__(self, config: TransportConfig) -> None:
        self.config = config

    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        path = f"{self.config.endpoint_url.rstrip('/')}/vehicles/{vehicle_id}/commands"
        body = json.dumps(payload).encode("utf-8")

        for attempt in range(1, self.config.retry.max_attempts + 1):
            headers = {"Content-Type": "application/json"}
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            req = request.Request(path, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.config.timeout_s) as response:
                    if 200 <= response.status < 300:
                        return
                    raise AdapterExecutionError(f"http status {response.status}")
            except (error.HTTPError, error.URLError, TimeoutError, AdapterExecutionError) as exc:
                if attempt >= self.config.retry.max_attempts:
                    raise AdapterExecutionError(f"http transport failed: {exc}") from exc
                delay = self.config.retry.backoff_s * (2 ** (attempt - 1))
                time.sleep(delay)


class MqttCommandTransport(CommandTransport):
    def __init__(self, config: TransportConfig) -> None:
        self.config = config
        self.published: list[tuple[str, dict[str, object]]] = []

    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        for attempt in range(1, self.config.retry.max_attempts + 1):
            try:
                if self.config.endpoint_url.startswith("fail://"):
                    raise AdapterExecutionError("mqtt broker unavailable")
                topic = f"vehicles/{vehicle_id}/commands"
                self.published.append((topic, payload))
                return
            except AdapterExecutionError as exc:
                if attempt >= self.config.retry.max_attempts:
                    raise
                delay = self.config.retry.backoff_s * (2 ** (attempt - 1))
                time.sleep(delay)
