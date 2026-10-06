"""WebSocket ASR streaming endpoint.

Receives 16 kHz / 16-bit / mono PCM audio frames over WebSocket and returns
JSON messages with partial and final recognition results.

Protocol
--------
Client → Server
  - Binary frame: raw PCM audio (16-bit signed, little-endian, mono, 16 kHz)
  - JSON frame (optional): ``{"type": "config", "sample_rate": 16000}``

Server → Client
  - ``{"type": "status", "state": "loading" | "ready"}``
  - ``{"type": "partial", "text": "..."}``
  - ``{"type": "final",   "text": "..."}``
  - ``{"type": "error",   "message": "..."}``

Auth
----
The JWT token is passed as a **query parameter** ``?token=<jwt>`` because
browsers cannot set custom headers on WebSocket connections.  Localhost
connections (127.0.0.1 / ::1) are exempt from auth, mirroring the REST API
behaviour in ``main.py``.
"""

import asyncio
import ipaddress
import json
import logging
import struct
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.asr.service import ASRService
from app.services.auth_service import AuthService

logger = logging.getLogger("broca.asr.ws")

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pcm_to_float32(data: bytes) -> List[float]:
    """Convert 16-bit signed PCM bytes to a list of float32 in [-1.0, 1.0]."""
    # Handle possible trailing odd byte
    n = len(data) // 2
    if n == 0:
        return []
    samples = struct.unpack(f"<{n}h", data[: n * 2])
    return [s / 32768.0 for s in samples]


def _is_loopback(host: str | None) -> bool:
    """Return True if *host* is a loopback address (IPv4 or IPv6)."""
    if not host:
        return False
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            return addr.ipv4_mapped.is_loopback
        return addr.is_loopback
    except ValueError:
        return False


async def _authenticate_websocket(ws: WebSocket) -> None:
    """Authenticate a WebSocket connection.

    * Loopback connections are allowed without a token (same as REST API).
    * Remote connections must supply a valid ``?token=<jwt>`` query param.
    """
    client_host = ws.headers.get(
        "x-real-ip"
    ) or (ws.client.host if ws.client else None)

    if _is_loopback(client_host):
        return

    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=1008, reason="Missing token")
        raise WebSocketDisconnect(code=1008)

    try:
        AuthService.decode_access_token(token)
    except Exception:
        await ws.close(code=1008, reason="Invalid token")
        raise WebSocketDisconnect(code=1008)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/asr/stream")
async def asr_stream_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint for streaming ASR.

    Path: ``/api/asr/stream``
    """
    # --- Auth -----------------------------------------------------------
    try:
        await _authenticate_websocket(ws)
    except WebSocketDisconnect:
        return

    await ws.accept()
    asr = ASRService.get_instance()
    stream = None

    try:
        # --- Lazy-load the model ----------------------------------------
        await ws.send_json({"type": "status", "state": "loading"})
        try:
            await asr.ensure_loaded()
        except Exception as exc:
            logger.error("ASR model load failed: %s", exc)
            await ws.send_json(
                {"type": "error", "message": f"Failed to load ASR model: {exc}"}
            )
            await ws.close(code=1011)
            return

        await ws.send_json({"type": "status", "state": "ready"})

        # --- Create per-connection stream --------------------------------
        stream = asr.create_session()

        # --- Main receive loop -------------------------------------------
        last_sent_text: str = ""
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Binary frame → audio data
            if "bytes" in message and message["bytes"] is not None:
                data: bytes = message["bytes"]
                samples = _pcm_to_float32(data)
                if not samples:
                    continue

                text, is_final = asr.process_audio(stream, samples)
                if logger.isEnabledFor(logging.DEBUG):
                    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5 if samples else 0
                    logger.debug(
                        "ASR WS: frame=%d bytes(%.0fms) rms=%.4f → %s=%r",
                        len(data), len(data) / 2 / 16000 * 1000, rms,
                        "final" if is_final else "partial", text,
                    )
                if text:
                    # 跳过与上次相同的 partial，减少 WebSocket 消息量；
                    # final 始终发送（endpoint 是语义边界）
                    if is_final or text != last_sent_text:
                        await ws.send_json(
                            {"type": "final" if is_final else "partial", "text": text}
                        )
                        last_sent_text = text
                    if is_final:
                        last_sent_text = ""  # 重置，下一句从空开始

            # Text frame → JSON control message
            elif "text" in message and message["text"]:
                try:
                    payload: Dict[str, Any] = json.loads(message["text"])
                except Exception:
                    logger.warning("ASR WS: invalid JSON frame ignored: %s", message["text"][:100])
                    continue

                msg_type = payload.get("type")
                if msg_type == "config":
                    # Acknowledge config; we currently only support 16 kHz
                    sr = payload.get("sample_rate", 16000)
                    if sr != 16000:
                        await ws.send_json(
                            {
                                "type": "error",
                                "message": f"Unsupported sample_rate {sr}. Only 16000 is supported.",
                            }
                        )
                # Other control types are silently ignored

    except WebSocketDisconnect:
        logger.info("ASR WS: client disconnected")
    except Exception:
        logger.exception("ASR WS: unexpected error")
    finally:
        # --- Cleanup ------------------------------------------------------
        if stream is not None and asr.is_loaded():
            try:
                final_text = asr.finish_session(stream)
                if final_text:
                    logger.debug("ASR WS: final text on disconnect: %r", final_text)
            except Exception:
                logger.exception("ASR WS: error during session cleanup")
        logger.info("ASR WS: session cleaned up")

