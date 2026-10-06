"""ASR service core — lazy-loading singleton wrapping Sherpa-ONNX OnlineRecognizer.

Provides streaming speech recognition with:
  - Lazy model loading (on first ensure_loaded() call)
  - Per-connection session isolation (each WebSocket gets its own OnlineStream)
  - Endpoint detection with auto-reset for continuous speech
"""

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import sherpa_onnx

from app.asr.config import ASRConfig, get_asr_config

logger = logging.getLogger("broca.asr")


class ASRService:
    """Process-level singleton that manages the Sherpa-ONNX streaming recognizer.

    The underlying OnlineRecognizer is lazily loaded on the first call to
    ``ensure_loaded()``.  Each WebSocket connection creates its own
    ``OnlineStream`` via :meth:`create_session` so that concurrent users
    do not interfere with each other.
    """

    _instance: Optional["ASRService"] = None
    _init_lock = asyncio.Lock()

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._recognizer: Optional[sherpa_onnx.OnlineRecognizer] = None
        self._loading = False
        self._config: Optional[ASRConfig] = None

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "ASRService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------
    async def ensure_loaded(self) -> None:
        """Lazily initialise the OnlineRecognizer.

        Safe to call from multiple coroutines concurrently — only the first
        call performs the actual (blocking) model load; all others await the
        same lock and return immediately once loading is done.
        """
        if self._recognizer is not None:
            return

        async with self._lock:
            # Double-check after acquiring the lock
            if self._recognizer is not None:
                return

            self._loading = True
            self._config = get_asr_config()
            cfg = self._config
            logger.info("ASR: loading model '%s' …", cfg.model_name)

            try:
                t0 = time.monotonic()

                # Build the recognizer via the factory method.
                # This is a *blocking* call (model load takes ~1-3 s), so we
                # offload it to a thread to keep the event loop responsive.
                self._recognizer = await asyncio.to_thread(
                    _build_recognizer, cfg
                )

                elapsed = time.monotonic() - t0
                logger.info(
                    "ASR: model '%s' loaded in %.2fs",
                    cfg.model_name,
                    elapsed,
                )
            except Exception:
                logger.exception("ASR: failed to load model")
                self._recognizer = None
                raise
            finally:
                self._loading = False

    def is_loaded(self) -> bool:
        return self._recognizer is not None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def create_session(self) -> sherpa_onnx.OnlineStream:
        """Create an independent OnlineStream for a WebSocket connection."""
        if self._recognizer is None:
            raise RuntimeError(
                "ASR model not loaded. Call ensure_loaded() first."
            )
        return self._recognizer.create_stream()

    # ------------------------------------------------------------------
    # Audio processing
    # ------------------------------------------------------------------
    def process_audio(
        self,
        stream: sherpa_onnx.OnlineStream,
        samples: List[float],
    ) -> Tuple[str, bool]:
        """Feed audio samples into the stream and return the recognition state.

        Returns:
            (text, is_final)
            - ``text``: current partial (or final) recognition text
            - ``is_final``: True when endpoint detection fired (speech pause)
        """
        if self._recognizer is None:
            return ("", False)

        rec = self._recognizer
        sample_rate = self._config.sample_rate if self._config else 16000
        cfg = self._config

        # --- Noise gate: replace very quiet frames with silence ---
        if cfg and cfg.noise_gate_rms > 0:
            rms = _compute_rms(samples)
            if rms < cfg.noise_gate_rms:
                samples = [0.0] * len(samples)

        # Feed audio into the stream
        stream.accept_waveform(sample_rate, samples)

        # Decode all ready chunks
        while rec.is_ready(stream):
            rec.decode_stream(stream)

        # Endpoint detection → final result for this utterance
        if rec.is_endpoint(stream):
            text = _dedup_consecutive(rec.get_result(stream))
            rec.reset(stream)  # reset so the stream can accept the next utterance
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("ASR: endpoint fired, final=%r", text)
            return (text, True)

        # Otherwise, return the current partial hypothesis
        text = _dedup_consecutive(rec.get_result(stream))
        return (text, False)

    # ------------------------------------------------------------------
    # Session teardown
    # ------------------------------------------------------------------
    def finish_session(
        self, stream: sherpa_onnx.OnlineStream
    ) -> str:
        """End a session: flush remaining audio, return final text, release stream."""
        if self._recognizer is None:
            return ""

        rec = self._recognizer
        stream.input_finished()

        while rec.is_ready(stream):
            rec.decode_stream(stream)

        text = rec.get_result(stream)
        # The stream is garbage-collected once no more references exist.
        return text


def _compute_rms(samples: List[float]) -> float:
    """Compute RMS energy of a sample list."""
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


#: 连续重复字符的最大允许次数（超过则截断）。
#: 中文里同一字连续出现 4 次以上几乎不可能是真实语音，
#: 绝大多数情况是 transducer 解码器"卡住"产生的重复。
_MAX_CONSECUTIVE_REP = 4


def _dedup_consecutive(text: str) -> str:
    """截断连续重复字符，防止模型解码卡住导致 '哈' x N 的情况。"""
    if not text:
        return text
    result: list[str] = []
    run_char = ""
    run_count = 0
    for ch in text:
        if ch == run_char:
            run_count += 1
            if run_count > _MAX_CONSECUTIVE_REP:
                continue  # 丢弃超出的重复
        else:
            run_char = ch
            run_count = 1
        result.append(ch)
    return "".join(result)


def _build_recognizer(cfg: ASRConfig) -> sherpa_onnx.OnlineRecognizer:
    """Blocking helper that creates the OnlineRecognizer (runs in a thread)."""
    logger.info("ASR: decoding_method=%s, noise_gate_rms=%s",
                cfg.decoding_method, cfg.noise_gate_rms)
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(cfg.tokens_path),
        encoder=str(cfg.encoder_path),
        decoder=str(cfg.decoder_path),
        joiner=str(cfg.joiner_path),
        num_threads=cfg.num_threads,
        sample_rate=cfg.sample_rate,
        provider=cfg.provider,
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=1.2,
        rule3_min_utterance_length=20.0,
        decoding_method=cfg.decoding_method,
        debug=False,
    )
