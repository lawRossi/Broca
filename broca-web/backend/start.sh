#!/bin/bash
# Start Broca backend service.

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BACKEND_DIR"

# Fix sherpa-onnx dylib path on macOS (libonnxruntime.dylib symlink)
if [ "$(uname)" = "Darwin" ]; then
    SHERPA_LIB=$(python3 -c "import sherpa_onnx, os; print(os.path.join(os.path.dirname(sherpa_onnx.__file__), 'lib'))" 2>/dev/null)
    if [ -n "$SHERPA_LIB" ] && [ ! -e "$SHERPA_LIB/libonnxruntime.dylib" ]; then
        OR_DYLIB=$(find "$(python3 -c 'import onnxruntime, os; print(os.path.dirname(onnxruntime.__file__))')" -name 'libonnxruntime*.dylib' 2>/dev/null | head -1)
        if [ -n "$OR_DYLIB" ]; then
            ln -sf "$OR_DYLIB" "$SHERPA_LIB/libonnxruntime.dylib"
        fi
    fi
fi

# Pre-download ASR model in the background (non-blocking, first-run only)
if [ -f "scripts/download_asr_model.py" ]; then
    MODEL_DIR="$HOME/.broca/models/asr"
    if [ ! -d "$MODEL_DIR/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30" ] \
       || [ -z "$(ls "$MODEL_DIR/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30" 2>/dev/null)" ]; then
        echo "[start] Pre-downloading ASR model in background…"
        python3 scripts/download_asr_model.py >> /tmp/broca-asr-download.log 2>&1 &
    fi
fi

nohup uvicorn app.main:app --port 9000 2>&1 &
