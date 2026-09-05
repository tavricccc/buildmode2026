from __future__ import annotations

import asyncio
import json
import os
from typing import Awaitable, Callable


class FrigateMqttWorker:
    """Optional Frigate MQTT lifecycle adapter.

    Frigate publishes JSON on frigate/events. This worker normalizes only the
    event metadata and hands it to the same noteworthy gate as HTTP events.
    """

    def __init__(self, on_event: Callable[[dict], Awaitable[dict]]):
        self.on_event = on_event
        self.client = None
        self.native_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.status = "unavailable"
        self.error: str | None = "FRIGATE_MQTT_NOT_CONFIGURED"

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        host = os.getenv("FRIGATE_MQTT_HOST", "").strip()
        if not host:
            return
        try:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="care-agent-frigate")
            username = os.getenv("FRIGATE_MQTT_USERNAME", "")
            password = os.getenv("FRIGATE_MQTT_PASSWORD", "")
            if username:
                self.client.username_pw_set(username, password)
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.connect_async(host, int(os.getenv("FRIGATE_MQTT_PORT", "1883")), 30)
            self.client.loop_start()
            self.status = "starting"
            self.error = None
        except ImportError:
            # Keep the event path runnable in a minimal Python environment.
            # This is a deliberately small QoS 0 MQTT 3.1.1 subscriber.
            self.status = "starting"
            self.error = None
            self.native_task = loop.create_task(self._native_loop(host, int(os.getenv("FRIGATE_MQTT_PORT", "1883")), os.getenv("FRIGATE_MQTT_TOPIC", "frigate/events")))
        except (OSError, ValueError):
            self.status = "unavailable"
            self.error = "FRIGATE_MQTT_ADAPTER_UNAVAILABLE"

    @staticmethod
    def _length(value: int) -> bytes:
        encoded = bytearray()
        while True:
            digit = value % 128
            value //= 128
            if value:
                digit |= 128
            encoded.append(digit)
            if not value:
                return bytes(encoded)

    @staticmethod
    def _string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return len(raw).to_bytes(2, "big") + raw

    def _connect_packet(self, client_id: str, username: str = "", password: str = "") -> bytes:
        flags = 0x02
        payload = self._string(client_id)
        if username:
            flags |= 0x80
            payload += self._string(username)
            if password:
                flags |= 0x40
                payload += self._string(password)
        variable = b"\x00\x04MQTT\x04" + bytes([flags]) + (60).to_bytes(2, "big")
        body = variable + payload
        return bytes([0x10]) + self._length(len(body)) + body

    def _subscribe_packet(self, topic: str) -> bytes:
        body = (1).to_bytes(2, "big") + self._string(topic) + b"\x00"
        return bytes([0x82]) + self._length(len(body)) + body

    async def _read_packet(self, reader: asyncio.StreamReader) -> tuple[int, bytes]:
        first = (await reader.readexactly(1))[0]
        multiplier = 1; remaining = 0
        while True:
            digit = (await reader.readexactly(1))[0]
            remaining += (digit & 127) * multiplier
            if digit & 128 == 0: break
            multiplier *= 128
            if multiplier > 128 * 128 * 128: raise ValueError("invalid MQTT remaining length")
        return first >> 4, await reader.readexactly(remaining)

    @staticmethod
    def _publish_payload(packet_type: int, body: bytes, flags: int = 0) -> bytes | None:
        if packet_type != 3 or len(body) < 2:
            return None
        topic_len = int.from_bytes(body[:2], "big")
        index = 2 + topic_len
        qos = (flags >> 1) & 0x03
        if qos:
            index += 2
        return body[index:]

    async def _native_loop(self, host: str, port: int, topic: str) -> None:
        client_id = "care-agent-frigate-native"
        username = os.getenv("FRIGATE_MQTT_USERNAME", "")
        password = os.getenv("FRIGATE_MQTT_PASSWORD", "")
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(host, port)
                writer.write(self._connect_packet(client_id, username, password)); await writer.drain()
                packet_type, body = await asyncio.wait_for(self._read_packet(reader), 8)
                if packet_type != 2 or len(body) < 2 or body[1] != 0:
                    raise ConnectionError("MQTT CONNACK rejected")
                writer.write(self._subscribe_packet(topic)); await writer.drain()
                await self._read_packet(reader)
                self.status = "healthy"; self.error = None
                while True:
                    packet_type, body = await asyncio.wait_for(self._read_packet(reader), 55)
                    if packet_type == 3:
                        payload = self._publish_payload(packet_type, body, 0)
                        if payload:
                            try:
                                normalized = self.normalize(json.loads(payload.decode("utf-8")))
                                if normalized: await self.on_event(normalized)
                            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                                continue
                    elif packet_type == 13:
                        writer.write(b"\xd0\x00"); await writer.drain()
                    else:
                        # Keepalive traffic and PUBACK/SUBACK do not affect the domain path.
                        continue
            except asyncio.CancelledError:
                if writer: writer.close()
                raise
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError):
                self.status = "unavailable"; self.error = "FRIGATE_MQTT_CONNECT_FAILED"
                if writer: writer.close()
                await asyncio.sleep(3)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if int(reason_code) == 0:
            client.subscribe(os.getenv("FRIGATE_MQTT_TOPIC", "frigate/events"))
            self.status = "healthy"
            self.error = None
        else:
            self.status = "unavailable"
            self.error = "FRIGATE_MQTT_CONNECT_FAILED"

    def _on_message(self, client, userdata, message):
        if not self.loop:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            normalized = self.normalize(payload)
            if normalized:
                asyncio.run_coroutine_threadsafe(self.on_event(normalized), self.loop)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return

    @staticmethod
    def normalize(payload: dict) -> dict | None:
        after = payload.get("after") or payload.get("event") or payload
        if not isinstance(after, dict):
            return None
        event_id = str(payload.get("id") or after.get("id") or "")
        camera = str(after.get("camera") or payload.get("camera") or "")
        label = str(after.get("label") or payload.get("label") or "person")
        started = after.get("start_time") or payload.get("start_time")
        if not event_id or not camera or started is None:
            return None
        from datetime import datetime, timezone
        if isinstance(started, (int, float)):
            started = datetime.fromtimestamp(started, timezone.utc).isoformat()
        ended = after.get("end_time") or payload.get("end_time")
        if isinstance(ended, (int, float)):
            ended = datetime.fromtimestamp(ended, timezone.utc).isoformat()
        return {"frigate_event_id": event_id, "camera": camera, "label": label,
                "score": after.get("top_score") or after.get("score"),
                "update_type": payload.get("type") if payload.get("type") in {"start", "update", "end"} else "update",
                "zones": after.get("current_zones") or after.get("zones") or [], "started_at": started, "ended_at": ended,
                "snapshot_uri": None if not after.get("has_snapshot") else f"frigate://{event_id}/snapshot",
                "clip_uri": None if not after.get("has_clip") else f"frigate://{event_id}/clip", "noteworthy": None}

    def stop(self) -> None:
        if self.native_task:
            self.native_task.cancel()
            self.native_task = None
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except OSError:
                pass
            self.client = None
        self.status = "stopped"
