# 语音输入功能 — Phase 1: 后端 ASR 服务 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/voice-input-asr-plan.md |
| Phase | Phase 1: 后端 ASR 服务 |
| Status | ⚠️ Partial (code complete, model-dependent ACs blocked by network) |

## Plan Anchor Confirmation

- [x] Re-read the plan document section for this phase before starting
- [x] Acceptance criteria for each task confirmed

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 1.1: 添加 Sherpa-ONNX 依赖与模型管理 | ⚠️ | (1) poetry install + import sherpa_onnx (2) download model files (3) skip existing (4) BROCA_ASR_MODEL override | (1)✅ v1.13.8 (2)⚠️ script correct, network blocked (3)✅ verified (4)✅ verified | Added onnxruntime as explicit dep (macOS dylib fix). start.sh includes dylib symlink step |
| Task 1.2: 实现 ASR 服务核心 | ⚠️ | (1) singleton (2) load timing (3) full flow (4) 5 concurrent (5) endpoint reset (6) not-loaded guard | (1)✅ (2)⚠️ untestable (3)⚠️ untestable (4)⚠️ untestable (5)✅ code correct (6)✅ returns "" | API adapted: from_transducer() instead of config objects (plan used outdated API) |
| Task 1.3: 实现 WebSocket ASR 端点 | ⚠️ | (1) connect→ready (2) audio→partial/final (3) English audio (4) no token→403 (5) 2 concurrent (6) cleanup (7) health OK | (1)✅ loading received (2)⚠️ untestable (3)⚠️ untestable (4)✅ auth logic correct (5)✅ verified (6)✅ verified (7)✅ verified | HTTPBearer incompatible with WS → moved auth to router level. main.py restructured |

> ⚠️ = Partial (code correct, but model-dependent ACs can't be verified without model files — network access to GitHub/HuggingFace is blocked in this environment)

## Deviations

### 1. Added `onnxruntime` as explicit dependency
**What**: Added `onnxruntime (>=1.16.0)` to pyproject.toml.
**Why**: sherpa-onnx's macOS wheel references `libonnxruntime.dylib` which isn't bundled. The dylib symlink to onnxruntime's install is created in start.sh.
**Impact**: None — onnxruntime is already a transitive dep.

### 2. `verify_token` auth restructured to router level
**What**: Changed from `FastAPI(dependencies=[Depends(verify_token)])` to `app.include_router(api_router, dependencies=[Depends(verify_token)])`. ASR WebSocket router registered separately without the dependency.
**Why**: `HTTPBearer` security scheme is incompatible with WebSocket routes — it calls `__call__(request)` which fails when a `WebSocket` object is passed instead of `Request`.
**Impact**: All existing HTTP routes still use the same auth. Only WebSocket routes are exempt (they have their own auth).

### 3. API adapted from plan
**What**: Plan referenced `OnlineRecognizerConfig` / `OnlineModelConfig` which don't exist in sherpa-onnx 1.13.8. Used `OnlineRecognizer.from_transducer()` factory method instead.
**Why**: The actual sherpa-onnx Python API uses factory methods with keyword arguments.
**Impact**: Functionally equivalent, code is cleaner.

## Quality Checklist

- [x] All phase-level ACs addressed (model-dependent ones blocked by environment)
- [x] All task-level ACs addressed
- [x] No missing tasks (3/3 tasks implemented)
- [x] No extra functionality
- [x] Manually verified key behaviors (WS connect, concurrent, error handling, health check)
- [x] Code follows project conventions (logging, type hints, docstrings)
- [x] Compatible with existing work (health check, auth, API router all still function)

## Files Changed

| File | Action |
|------|--------|
| `broca-web/backend/pyproject.toml` | Modified — added sherpa-onnx, onnxruntime |
| `broca-web/backend/app/asr/__init__.py` | Created |
| `broca-web/backend/app/asr/config.py` | Created |
| `broca-web/backend/app/asr/service.py` | Created |
| `broca-web/backend/app/api/asr.py` | Created |
| `broca-web/backend/app/api/__init__.py` | Modified (no changes needed after restructure) |
| `broca-web/backend/app/main.py` | Modified — auth restructured to router level, ASR router registered |
| `broca-web/backend/scripts/download_asr_model.py` | Created |
| `broca-web/backend/start.sh` | Modified — dylib fix + model pre-download |

## Remaining Items (require network access)

- Download ASR model files → enables full recognition testing
- Test with actual Chinese/English audio → verify recognition accuracy
- Test model load timing (first call vs subsequent)
