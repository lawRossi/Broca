#!/usr/bin/env python3
"""Download Sherpa-ONNX ASR model files from ModelScope.

Usage:
    python download_asr_model.py [--model MODEL_NAME]

Downloads the specified streaming ASR model to ~/.broca/models/asr/{model_name}/.
Files already present on disk are skipped.
"""

import argparse
import sys
from pathlib import Path

# Model IDs by source (owner/model_name)
# ModelScope mirrors (faster in China)
MODELSCOPE_MODEL_IDS = {
    "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20":
        "pkufool/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
    "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23":
        "pkufool/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23",
    "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17":
        "pkufool/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
}

# HuggingFace repos (official source, all models available)
HUGGINGFACE_MODEL_IDS = {
    "sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30":
        "csukuangfj/sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30",
    "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30":
        "csukuangfj/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
    "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20":
        "csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
}

DEFAULT_MODEL = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"

MODEL_DIR = Path.home() / ".broca" / "models" / "asr"


def _log(msg: str) -> None:
    print(f"[ASR Download] {msg}", flush=True)


def download_model(model_name: str) -> None:
    """Download model files for the given model from ModelScope.

    Strategy:
    1. If the model directory already has the required files, skip.
    2. Use modelscope SDK snapshot_download to fetch missing files.
    """
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

    # Determine download source: prefer ModelScope (fast in China), fallback to HuggingFace
    modelscope_id = MODELSCOPE_MODEL_IDS.get(model_name)
    huggingface_id = HUGGINGFACE_MODEL_IDS.get(model_name)

    missing = [k for k, v in required.items() if not v]
    if missing:
        _log(f"Missing: {', '.join(missing)}")
    _log(f"Target directory: {dest_dir}")

    # Download all .onnx model files + tokenizer files.
    allow_patterns = [
        "*.onnx",
        "tokens.txt",
        "bpe.model",
    ]

    downloaded = False

    # Try ModelScope first
    if modelscope_id:
        _log(f"Trying ModelScope: {modelscope_id}")
        try:
            from modelscope.hub.snapshot_download import snapshot_download
            snapshot_download(
                modelscope_id,
                local_dir=str(dest_dir),
                allow_patterns=allow_patterns,
                max_workers=4,
            )
            downloaded = True
            _log("Download complete (ModelScope).")
        except ImportError:
            _log("ModelScope SDK not installed, trying HuggingFace...")
        except Exception as e:
            _log(f"ModelScope download failed: {e}")

    # Fallback to HuggingFace
    if not downloaded and huggingface_id:
        _log(f"Trying HuggingFace: {huggingface_id}")
        try:
            from huggingface_hub import snapshot_download as hf_download
            hf_download(
                huggingface_id,
                local_dir=str(dest_dir),
                allow_patterns=allow_patterns,
                max_workers=4,
            )
            downloaded = True
            _log("Download complete (HuggingFace).")
        except ImportError:
            _log("ERROR: Neither 'modelscope' nor 'huggingface_hub' is installed.")
            _log("Install one with: pip install modelscope  OR  pip install huggingface_hub")
            raise SystemExit(1)
        except Exception as e:
            _log(f"HuggingFace download failed: {e}")
            _log(f"You can also download manually: "
                 f"hf download {huggingface_id} "
                 f'--include "*.onnx" "tokens.txt" "bpe.model" '
                 f"--local-dir {dest_dir}")
            raise SystemExit(1)

    if not downloaded:
        _log("ERROR: No download source available for this model.")
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
    parser = argparse.ArgumentParser(description="Download Sherpa-ONNX ASR model from ModelScope")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()
    download_model(args.model)


if __name__ == "__main__":
    main()
