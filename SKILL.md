---
name: hbg-gemini-flow-suite
description: Deploy, authorize, operate, diagnose, and update the Docker-based HBG Gemini Flow Suite for Gemini Web image/video generation and Google Flow/Veo image or video generation. Use for Docker-only Gemini/Flow workflows, Flow Omni Flash reference-to-video (素材图生视频), Veo first/end-frame generation, Apple Silicon Flow compatibility, local Chrome authorization, generated-media download, and Flow UI selector breakages.
---

# HBG Gemini Flow Suite

Operate this repository through `./suite`. Keep Google credentials, browser profiles, generated account data, and `.env` outside Git.

## Deploy

1. Check Docker, Docker Compose v2, and host Chrome/Chromium.
2. Copy `.env.example` to `.env` when `.env` is absent.
3. Require the user to replace `NOVNC_PASSWORD` before first startup.
4. Run `./suite build`, `./suite up`, and `./suite status`.
5. Treat `./suite status` as a saved-profile check, not proof that Google will accept a new generation request.

On Apple Silicon, keep `FLOW_RUNNER_MODE=auto`. The suite uses the native `linux/arm64` Flow runner while retaining the main `linux/amd64` media container for Gemini and cleanup features.

## Authorize

Run authorization only through the dedicated local profiles:

```bash
./suite auth gemini
./suite auth flow
```

Ask the user to complete Google login in the opened Chrome window and press Enter only after the target product page is available. For Flow, require the actual Flow home/project page; a URL ending in `/api/auth/signin?error=Callback` is not successful authorization.

The macOS workflow temporarily bridges Docker Desktop to the localhost-only Chrome CDP port. Keep the bridge process bounded to the command and never expose a persistent remote-debugging port.

## Choose the correct video mode

Use reference-to-video for one or more complete visual ingredients:

```bash
./suite flow video r2v \
  "Animate this exact reference image as one continuous cinematic shot" \
  --ref /workspace/reference.png \
  --model omni-flash \
  --duration 8 \
  --aspect 16:9 \
  --count 1 \
  --out-dir flow/videos/reference-shot \
  --json
```

Use `video r2v` for Flow's **References / 素材** mode. Do not substitute `video i2v --initial-frame` when the user explicitly wants a complete image treated as a visual reference rather than a seeded first frame.

Use first/end-frame generation only when the user explicitly wants controlled interpolation:

```bash
./suite flow video i2v \
  --initial-frame /workspace/start.png \
  --end-frame /workspace/end.png \
  "One continuous physically plausible transition" \
  --model veo-quality \
  --duration 8 \
  --aspect 16:9 \
  --out-dir flow/videos/frame-transition \
  --json
```

Use Gemini Web image-to-video when requested:

```bash
./suite gemini video \
  "Animate this exact image as one slow cinematic shot" \
  --image /workspace/reference.png \
  --out-dir gemini/videos/image-to-video
```

## Verify real submission

Do not claim that video generation started merely because the editor opened or an image uploaded. Require logs that show:

1. The expected video submode was entered (`references` or `frames`).
2. Every required image upload returned success.
3. The reference/frame was attached.
4. `send_prompt` completed.
5. The generation request returned HTTP 200 or an equivalent submitted event.
6. Status polling began.

Treat `MEDIA_GENERATION_STATUS_SUCCESSFUL` as server-side generation success even when the later local download fails. Recover the existing media instead of regenerating and spending credits again.

## Diagnose Flow updates

When Flow changes its UI:

1. Record the current gflow version, locale, model, submode, aspect, duration, and count.
2. Read structured logs and the local incident bundle under `/data/gflow/incidents`.
3. Distinguish authorization, selector, upload, submit, polling, and download failures.
4. Preserve older selectors while adding the new cohort.
5. Prefer locale-independent attributes, roles, tab IDs, and Material Symbols ligatures.
6. Fail closed when output count cannot be selected; never risk silently using x2 instead of x1.
7. Run deterministic checks before retrying a credit-bearing generation.

Current compatibility hooks in `sitecustomize.py` cover:

- native button-based start/end-frame slots;
- `x1` and legacy `1x` output-count labels;
- host-CDP attachment without closing the dedicated host browser;
- stale Chromium Singleton cleanup;
- reliable Create-button prompt submission;
- no-op reference-entity interception avoidance.

## Validate changes

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q suite_cli.py media_cleanup.py sync_auth.py sitecustomize.py scripts/cdp_bridge.py
sh -n suite start-desktop.sh
python3 scripts/check_secrets.py
NOVNC_PASSWORD=local-test docker compose --env-file .env.example config --quiet
docker build --platform linux/arm64 -f Dockerfile.arm64-flow --build-arg GFLOW_VERSION=0.53.1 .
```

For browser-automation changes, also report the tested Flow locale, UI date, command mode, model, aspect ratio, duration, and whether the request reached actual submission.
