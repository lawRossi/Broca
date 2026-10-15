#!/usr/bin/env python3
"""Download Sherpa-ONNX ASR model files (INT8 models only).

Usage:
    python download_asr_model.py [--model MODEL_NAME]

Available models:
    sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30        (default, ~168 MB)
    sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30 (xlarge, ~400 MB)

Downloads via hf-mirror.com (HuggingFace China mirror) by default,
falls back to official huggingface.co if the mirror is unavailable.
Model files are saved to ~/.broca/models/asr/{model_name}/.
"""

import argparse
import os
import sys
from pathlib import Path

# HuggingFace repos (official source)
HF_MODEL_IDS = {
    "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30":
        "csukuangfj/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
    "sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30":
        "csukuangfj/sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30",
}

# 国内镜像
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
# 官方源（回退）
HF_OFFICIAL_ENDPOINT = "https://huggingface.co"

DEFAULT_MODEL = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"

MODEL_DIR = Path.home() / ".broca" / "models" / "asr"


def _log(msg: str) -> None:
    print(f"[ASR Download] {msg}", flush=True)


def _snapshot_download(repo_id: str, local_dir: str, endpoint: str) -> bool:
    """Try to download from the given endpoint. Returns True on success."""
    try:
        from huggingface_hub import snapshot_download
        # 通过环境变量切换端点
        os.environ["HF_ENDPOINT"] = endpoint
        snapshot_download(
            repo_id,
            local_dir=local_dir,
            allow_patterns=["*.onnx", "tokens.txt", "bpe.model"],
            max_workers=4,
        )
        return True
    except ImportError:
        _log("ERROR: 'huggingface_hub' is not installed.")
        _log("Install it with: pip install huggingface_hub")
        return False
    except Exception as e:
        _log(f"Download from {endpoint} failed: {e}")
        return False


def download_model(model_name: str) -> None:
    """Download model files for the given model."""
    if model_name not in HF_MODEL_IDS:
        _log(f"ERROR: Unknown model '{model_name}'")
        _log(f"Available models: {', '.join(HF_MODEL_IDS.keys())}")
        raise SystemExit(1)

    repo_id = HF_MODEL_IDS[model_name]
    dest_dir = MODEL_DIR / model_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Check if model is already fully downloaded
    required = {
        "encoder": list(dest_dir.glob("encoder*.onnx")),
        "decoder": list(dest_dir.glob("decoder*.onnx")),
        "joiner": list(dest_dir.glob("joiner*.onnx")),
        "tokens": list(dest_dir.glob("tokens.txt")),
    }
    if all(required[k] for k in required):
        _log(f"Model '{model_name}' already exists in {dest_dir}. Nothing to do.")
        return

    missing = [k for k, v in required.items() if not v]
    _log(f"Model: {model_name}")
    _log(f"Source:  {repo_id}")
    _log(f"Missing: {', '.join(missing)}")
    _log(f"Target:  {dest_dir}")

    # 优先使用国内镜像，失败后回退到官方源
    downloaded = _snapshot_download(repo_id, str(dest_dir), HF_MIRROR_ENDPOINT)
    if not downloaded:
        _log("Fallback to official HuggingFace...")
        downloaded = _snapshot_download(repo_id, str(dest_dir), HF_OFFICIAL_ENDPOINT)

    if not downloaded:
        _log("ERROR: Failed to download from both mirror and official source.")
        _log(f"  Mirror:   {HF_MIRROR_ENDPOINT}")
        _log(f"  Official: {HF_OFFICIAL_ENDPOINT}")
        _log(f"You can also try manually:  hf download {repo_id} "
             f'--include "*.onnx" "tokens.txt" "bpe.model" '
             f"--local-dir {dest_dir}")
        raise SystemExit(1)

    # Verify (re-glob after download)
    verified = {
        "encoder": list(dest_dir.glob("encoder*.onnx")),
        "decoder": list(dest_dir.glob("decoder*.onnx")),
        "joiner": list(dest_dir.glob("joiner*.onnx")),
        "tokens": list(dest_dir.glob("tokens.txt")),
    }
    failed = [k for k, v in verified.items() if not v]
    if failed:
        _log(f"ERROR: {', '.join(failed)} file(s) not found after download!")
        raise SystemExit(1)
    _log(f"✅ Model '{model_name}' ready in {dest_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Sherpa-ONNX INT8 ASR model (via hf-mirror.com)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=list(HF_MODEL_IDS.keys()),
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()
    download_model(args.model)


if __name__ == "__main__":
    main()
