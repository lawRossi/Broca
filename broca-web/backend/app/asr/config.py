"""ASR configuration.

Supports overriding the default model via:
  1. BROCA_ASR_MODEL / BROCA_ASR_DECODING / BROCA_ASR_NOISE_GATE env vars (highest priority)
  2. configs.json 的 asr 分组（Web 配置页可编辑）
  3. 代码内硬编码默认值
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ASRConfig:
    """Configuration for the ASR service."""

    #: Directory where ASR models are stored
    model_dir: Path = field(default=Path.home() / ".broca" / "models" / "asr")

    #: Name of the ASR model (subdirectory under model_dir)
    model_name: str = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"

    #: Number of threads for ONNX Runtime inference
    num_threads: int = field(default_factory=lambda: os.cpu_count() or 4)

    #: ONNX Runtime execution provider
    provider: str = "cpu"

    #: Expected audio sample rate (fixed for the streaming model)
    sample_rate: int = 16000

    #: Decoding method: "greedy_search" (fast) or "modified_beam_search" (more accurate)
    decoding_method: str = "modified_beam_search"

    #: RMS energy threshold for noise gating.
    #: Frames with RMS below this value are replaced with silence to
    #: prevent background noise from being transcribed ("多字").
    #: 0 disables the gate.  Default 0.005 ≈ -46 dB.
    noise_gate_rms: float = 0.005

    @property
    def model_path(self) -> Path:
        """Full path to the model directory."""
        return self.model_dir / self.model_name

    @property
    def encoder_path(self) -> Path:
        """Path to the encoder .onnx file (first match)."""
        candidates = sorted(self.model_path.glob("encoder*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"No encoder*.onnx found in {self.model_path}")
        return candidates[0]

    @property
    def decoder_path(self) -> Path:
        """Path to the decoder .onnx file (first match)."""
        candidates = sorted(self.model_path.glob("decoder*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"No decoder*.onnx found in {self.model_path}")
        return candidates[0]

    @property
    def joiner_path(self) -> Path:
        """Path to the joiner .onnx file (first match)."""
        candidates = sorted(self.model_path.glob("joiner*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"No joiner*.onnx found in {self.model_path}")
        return candidates[0]

    @property
    def tokens_path(self) -> Path:
        """Path to the tokens.txt file."""
        return self.model_path / "tokens.txt"

    def validate(self) -> None:
        """Check that the model files exist. Raises FileNotFoundError if not."""
        self.model_path  # trigger glob checks via properties below
        self.encoder_path
        self.decoder_path
        self.joiner_path
        if not self.tokens_path.exists():
            raise FileNotFoundError(f"tokens.txt not found in {self.model_path}")


def _read_asr_from_configs_json() -> dict:
    """从 configs.json 的 asr 分组读取配置（不存在时返回空 dict）。"""
    candidates = [
        os.getenv("BROCA_CONFIG"),
        str(Path.home() / ".broca" / "configs" / "configs.json"),
        str(Path.home() / ".broca" / "configs.json"),
    ]
    for path_str in candidates:
        if not path_str:
            continue
        path = Path(path_str).expanduser()
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                asr = data.get("asr")
                if isinstance(asr, dict):
                    return asr
            except (json.JSONDecodeError, OSError):
                pass
            break  # 找到第一个存在的文件即停止
    return {}


def get_asr_config() -> ASRConfig:
    """Create an ASRConfig.

    Priority (highest → lowest):
      1. Env vars: BROCA_ASR_MODEL / BROCA_ASR_DECODING / BROCA_ASR_NOISE_GATE
      2. configs.json → asr 分组（Web 配置页）
      3. 代码默认值
    """
    file_cfg = _read_asr_from_configs_json()
    kwargs = {}

    # model_name: env > file > default
    model_name = os.environ.get("BROCA_ASR_MODEL") or file_cfg.get("model_name")
    if model_name:
        kwargs["model_name"] = model_name

    # decoding_method: env > file > default
    decoding = os.environ.get("BROCA_ASR_DECODING") or file_cfg.get("decoding_method")
    if decoding:
        kwargs["decoding_method"] = decoding

    # noise_gate_rms: env > file > default
    noise_gate = os.environ.get("BROCA_ASR_NOISE_GATE")
    if noise_gate is not None:
        kwargs["noise_gate_rms"] = float(noise_gate)
    elif "noise_gate_rms" in file_cfg:
        kwargs["noise_gate_rms"] = float(file_cfg["noise_gate_rms"])

    return ASRConfig(**kwargs)
