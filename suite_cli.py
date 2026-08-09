from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from media_cleanup import clean_media, retain_or_remove_original


GFLOW = "/opt/gflow-venv/bin/gflow"
GEMINI_PYTHON = "/opt/gemini-venv/bin/python"
GEMINI_RUNNER = "/app/run_gemini.py"
OUTPUT_ROOT = Path(os.environ.get("MEDIA_OUTPUT_ROOT", "/data/outputs"))


def flag(name: str, default: bool) -> bool:
    fallback = "true" if default else "false"
    return os.environ.get(name, fallback).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    print(f"Running: {' '.join(command)}", flush=True)
    return subprocess.run(command, env=env).returncode


def normalized_output_dir(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else OUTPUT_ROOT / path


def pop_option(arguments: list[str], option: str) -> tuple[list[str], str | None]:
    cleaned: list[str] = []
    value: str | None = None
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == option:
            if index + 1 >= len(arguments):
                raise ValueError(f"{option} requires a value")
            value = arguments[index + 1]
            index += 2
            continue
        if item.startswith(option + "="):
            value = item.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(item)
        index += 1
    return cleaned, value


def clean_staged_files(staging: Path, final_dir: Path, media_type: str) -> list[dict[str, object]]:
    extensions = {".png", ".jpg", ".jpeg", ".webp"} if media_type == "image" else {".mp4", ".mov", ".webm"}
    sources = sorted(path for path in staging.rglob("*") if path.is_file() and path.suffix.lower() in extensions)
    if not sources:
        raise RuntimeError(f"Flow completed without a downloadable {media_type} file")

    final_dir.mkdir(parents=True, exist_ok=True)
    keep_originals = flag("KEEP_ORIGINALS", False)
    remove_marks = flag("REMOVE_VISIBLE_WATERMARKS", True)
    backend = os.environ.get("IMAGE_CLEAN_BACKEND", "migan")
    saved: list[dict[str, object]] = []

    for source in sources:
        final_name = f"{source.stem}_clean{source.suffix}" if remove_marks else source.name
        destination = final_dir / final_name
        if remove_marks:
            clean_media(source, destination, media_type, backend=backend)
            retained = retain_or_remove_original(source, final_dir, keep_originals)
        else:
            shutil.move(str(source), str(destination))
            retained = None
        saved.append(
            {
                "type": media_type,
                "path": str(destination),
                "visible_watermark_cleanup": remove_marks,
                "metadata_cleanup": remove_marks,
                "original_retained": retained,
            }
        )
    return saved


def write_flow_result(
    final_dir: Path,
    media_type: str,
    arguments: list[str],
    saved: list[dict[str, object]],
) -> None:
    payload = {
        "status": "complete",
        "provider": "flow",
        "media_type": media_type,
        "arguments": arguments,
        "saved": saved,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (final_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def flow_command(media_type: str, arguments: list[str]) -> int:
    if media_type == "raw":
        return run([GFLOW, *arguments])
    if not arguments:
        raise ValueError(f"flow {media_type} requires a gflow subcommand")

    output_option = "--out" if media_type == "image" else "--out-dir"
    arguments, requested_output = pop_option(arguments, output_option)
    final_dir = normalized_output_dir(
        requested_output,
        OUTPUT_ROOT / "flow" / ("images" if media_type == "image" else "videos"),
    )
    staging = OUTPUT_ROOT / ".processing" / f"flow-{media_type}-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=True)

    try:
        return_code = run([GFLOW, media_type, *arguments, output_option, str(staging)])
        if return_code != 0:
            return return_code
        saved = clean_staged_files(staging, final_dir, media_type)
        write_flow_result(final_dir, media_type, arguments, saved)
        print(json.dumps({"status": "complete", "saved": saved}, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def gemini_command(media_type: str, args: argparse.Namespace) -> int:
    output_dir = normalized_output_dir(
        args.out_dir,
        OUTPUT_ROOT / "gemini" / ("images" if media_type == "image" else "videos"),
    )
    env = os.environ.copy()
    env.update(
        {
            "GEMINI_ACTION": "generate",
            "GEMINI_MEDIA_TYPE": media_type,
            "GEMINI_PROMPT": args.prompt,
            "GEMINI_OUTPUT_DIR": str(output_dir),
            "GEMINI_MODEL": args.model or "",
            "GEMINI_INPUT_FILES": json.dumps(args.image or [], ensure_ascii=False),
            "GEMINI_REMOVE_WATERMARKS": "false" if args.no_clean else "true",
            "GEMINI_KEEP_ORIGINALS": "true" if args.keep_originals else env.get("KEEP_ORIGINALS", "false"),
        }
    )
    return run([GEMINI_PYTHON, GEMINI_RUNNER], env=env)


def status_command() -> int:
    gemini_cookie = Path(os.environ.get("GEMINI_COOKIE_FILE", "/data/auth/gemini/cookies.json"))
    gemini_ready = False
    if gemini_cookie.is_file():
        try:
            payload = json.loads(gemini_cookie.read_text(encoding="utf-8"))
            cookie_map = payload.get("cookieMap", payload) if isinstance(payload, dict) else {}
            gemini_ready = bool(cookie_map.get("__Secure-1PSID"))
        except Exception:
            gemini_ready = False

    flow_profile = Path(os.environ.get("GFLOW_CLI_HOME", "/data/gflow")) / "profile_flow"
    flow_ready = (flow_profile / "Default" / "Cookies").is_file() or (flow_profile / "Default" / "Network" / "Cookies").is_file()
    result = {
        "gemini_authorized": gemini_ready,
        "flow_authorized": flow_ready,
        "visible_watermark_cleanup": flag("REMOVE_VISIBLE_WATERMARKS", True),
        "output_root": str(OUTPUT_ROOT),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if gemini_ready and flow_ready else 2


def clean_command(args: argparse.Namespace) -> int:
    source = Path(args.source)
    output = Path(args.output)
    clean_media(source, output, args.media_type, backend=args.backend)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-suite",
        description="Unified Gemini Web + Google Flow image/video Docker CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    gemini = subparsers.add_parser("gemini")
    gemini_sub = gemini.add_subparsers(dest="media_type", required=True)
    for media_type in ("image", "video"):
        item = gemini_sub.add_parser(media_type)
        item.add_argument("prompt")
        item.add_argument("--model", default="")
        item.add_argument(
            "--image",
            action="append",
            default=[],
            help="Attach an input image inside the container, for example /workspace/start.png. Repeatable.",
        )
        item.add_argument("--out-dir")
        item.add_argument("--keep-originals", action="store_true")
        item.add_argument("--no-clean", action="store_true")

    flow = subparsers.add_parser("flow")
    flow.add_argument("media_type", choices=("image", "video", "raw"))
    flow.add_argument("arguments", nargs=argparse.REMAINDER)

    clean = subparsers.add_parser("clean")
    clean.add_argument("media_type", choices=("image", "video"))
    clean.add_argument("source")
    clean.add_argument("output")
    clean.add_argument("--backend", default=os.environ.get("IMAGE_CLEAN_BACKEND", "migan"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "status":
            return status_command()
        if args.command == "gemini":
            return gemini_command(args.media_type, args)
        if args.command == "flow":
            return flow_command(args.media_type, args.arguments)
        if args.command == "clean":
            return clean_command(args)
        raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
