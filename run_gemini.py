import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from gemini_webapi import GeminiClient
from media_cleanup import clean_media, retain_or_remove_original


def load_cookie_map(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict) and isinstance(data.get("cookieMap"), dict):
        data = data["cookieMap"]
    elif isinstance(data, list):
        data = {
            item.get("name"): item.get("value")
            for item in data
            if isinstance(item, dict) and item.get("name") and item.get("value")
        }

    if not isinstance(data, dict):
        raise ValueError("Unsupported cookie JSON format")

    cookie_map = {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(value, (str, int, float))
    }
    if not cookie_map.get("__Secure-1PSID"):
        raise ValueError("Cookie file does not contain __Secure-1PSID")
    return cookie_map


def model_summary(client: GeminiClient) -> list[dict[str, object]]:
    result = []
    for model in client.list_models() or []:
        result.append(
            {
                "model_name": getattr(model, "model_name", ""),
                "display_name": getattr(model, "display_name", ""),
                "description": getattr(model, "description", ""),
                "available": bool(getattr(model, "is_available", True)),
            }
        )
    return result


def write_result(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def should_redo_image(response_text: str) -> bool:
    text = response_text.lower()
    return (
        "limit resets" in text
        or "额度重置" in response_text
        or "用量重置" in response_text
    )


def env_flag(name: str, default: bool) -> bool:
    fallback = "true" if default else "false"
    return os.environ.get(name, fallback).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def final_output_path(source: Path, output_dir: Path) -> Path:
    return output_dir / f"{source.stem}_clean{source.suffix}"


def cleanup_generated_file(
    source_value: str,
    output_dir: Path,
    media_type: str,
    keep_originals: bool,
    image_backend: str,
) -> dict[str, object]:
    source = Path(source_value)
    output = final_output_path(source, output_dir)
    clean_media(source, output, media_type, backend=image_backend)
    retained_path = retain_or_remove_original(source, output_dir, keep_originals)
    return {
        "path": str(output),
        "watermark_cleanup": "complete",
        "visible_watermark_removed": True,
        "ai_metadata_removed": True,
        "original_retained": retained_path,
    }


async def save_generated_video(
    item: object,
    output_dir: Path,
    base_name: str,
    timeout: float,
    media: bool = False,
) -> dict[str, str | None]:
    kwargs = {"download_type": "video"} if media else {}
    return await asyncio.wait_for(
        item.save(
            path=str(output_dir),
            filename=base_name,
            verbose=True,
            **kwargs,
        ),
        timeout=timeout,
    )


async def save_generated_image(
    item: object,
    output_dir: Path,
    base_name: str,
    timeout: float,
    full_size: bool = True,
) -> str:
    return await asyncio.wait_for(
        item.save(
            path=str(output_dir),
            filename=base_name,
            verbose=True,
            full_size=full_size,
        ),
        timeout=timeout,
    )


async def main() -> int:
    cookie_file = Path(os.environ.get("GEMINI_COOKIE_FILE", "/run/secrets/gemini-cookies.json"))
    output_dir = Path(os.environ.get("GEMINI_OUTPUT_DIR", "/output"))
    action = os.environ.get("GEMINI_ACTION", "generate").strip().lower()
    media_type = os.environ.get("GEMINI_MEDIA_TYPE", "video").strip().lower()
    default_prompts = {
        "image": "Generate a high-quality cinematic image of a Hong Kong cha chaan teng at night.",
        "video": "Generate a short cinematic video of a Hong Kong cha chaan teng at night.",
    }
    if media_type not in default_prompts:
        raise ValueError(f"Unsupported GEMINI_MEDIA_TYPE: {media_type}")
    legacy_prompt_name = (
        "GEMINI_IMAGE_PROMPT" if media_type == "image" else "GEMINI_VIDEO_PROMPT"
    )
    prompt = os.environ.get(
        "GEMINI_PROMPT",
        os.environ.get(legacy_prompt_name, default_prompts[media_type]),
    ).strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    input_files_raw = os.environ.get("GEMINI_INPUT_FILES", "[]")
    try:
        input_files_value = json.loads(input_files_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("GEMINI_INPUT_FILES must be a JSON array") from exc
    if not isinstance(input_files_value, list) or not all(
        isinstance(item, str) and item.strip() for item in input_files_value
    ):
        raise ValueError("GEMINI_INPUT_FILES must contain non-empty path strings")
    input_files = [str(Path(item)) for item in input_files_value]
    missing_input_files = [item for item in input_files if not Path(item).is_file()]
    if missing_input_files:
        raise FileNotFoundError(
            "Gemini input file not found inside container: " + ", ".join(missing_input_files)
        )
    redo_model = os.environ.get("GEMINI_REDO_MODEL", "gemini-3-flash").strip()
    request_timeout = float(os.environ.get("GEMINI_REQUEST_TIMEOUT", "900"))
    download_timeout = float(os.environ.get("GEMINI_DOWNLOAD_TIMEOUT", "1200"))
    image_full_size = env_flag("GEMINI_IMAGE_FULL_SIZE", True)
    auto_redo = env_flag("GEMINI_AUTO_REDO", True)
    remove_watermarks = env_flag("GEMINI_REMOVE_WATERMARKS", True)
    keep_originals = env_flag("GEMINI_KEEP_ORIGINALS", False)
    image_backend = os.environ.get("GEMINI_IMAGE_CLEAN_BACKEND", "migan").strip()

    started_at = datetime.now(timezone.utc)
    result: dict[str, object] = {
        "started_at": started_at.isoformat(),
        "action": action,
        "media_type": media_type,
        "model": model or "auto",
        "prompt": prompt if action == "generate" else None,
        "input_files": input_files,
        "status": "starting",
        "saved": [],
        "automatic_watermark_cleanup": remove_watermarks,
    }

    cookie_map = load_cookie_map(cookie_file)
    client = GeminiClient(
        cookie_map["__Secure-1PSID"],
        cookie_map.get("__Secure-1PSIDTS"),
        proxy=os.environ.get("HTTPS_PROXY") or None,
    )

    try:
        print("Initializing Gemini Web client...", flush=True)
        await client.init(
            timeout=request_timeout,
            auto_close=False,
            auto_refresh=True,
            refresh_interval=600,
            watchdog_timeout=180,
            verbose=False,
        )

        result["account_status"] = getattr(client.account_status, "name", str(client.account_status))
        result["models"] = model_summary(client)
        print(f"Account status: {result['account_status']}", flush=True)
        print(f"Discovered models: {len(result['models'])}", flush=True)

        if action == "inspect":
            result["status"] = "inspection_complete"
            write_result(output_dir, result)
            return 0

        if action != "generate":
            raise ValueError(f"Unsupported GEMINI_ACTION: {action}")

        print(f"Submitting {media_type} generation request to Gemini Web...", flush=True)
        generate_kwargs = {
            "prompt": prompt,
            "temporary": False,
        }
        if input_files:
            generate_kwargs["files"] = input_files
        if model:
            generate_kwargs["model"] = model

        response = await asyncio.wait_for(
            client.generate_content(**generate_kwargs), timeout=request_timeout
        )
        result["initial_response_text"] = response.text
        result["redo_attempted"] = False

        initial_candidate = response.candidates[response.chosen]
        if (
            media_type == "image"
            and auto_redo
            and not initial_candidate.generated_images
            and should_redo_image(response.text)
        ):
            cid = response.metadata[0] if response.metadata else ""
            if cid:
                result["redo_attempted"] = True
                result["redo_chat_id"] = cid
                print(
                    "Gemini returned the image-limit placeholder; "
                    "redoing the same turn once...",
                    flush=True,
                )
                redo_kwargs: dict[str, object] = {
                    "metadata": [cid, "", ""],
                    "model": model or redo_model,
                }
                result["redo_model"] = model or redo_model
                redo_chat = client.start_chat(**redo_kwargs)
                response = await asyncio.wait_for(
                    redo_chat.send_message(prompt, temporary=False),
                    timeout=request_timeout,
                )
                result["redo_response_text"] = response.text

        result["response_text"] = response.text
        candidate = response.candidates[response.chosen]
        result["generated_image_count"] = len(candidate.generated_images)
        result["web_image_count"] = len(candidate.web_images)
        result["video_count"] = len(response.videos)
        result["media_count"] = len(response.media)
        print(
            "Gemini response received: "
            f"generated_images={len(candidate.generated_images)}, "
            f"web_images={len(candidate.web_images)}, "
            f"videos={len(response.videos)}, media={len(response.media)}",
            flush=True,
        )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved: list[dict[str, object]] = []
        staging_dir = output_dir / ".processing" / stamp
        download_dir = staging_dir if remove_watermarks else output_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        if media_type == "image":
            for index, generated_image in enumerate(candidate.generated_images, start=1):
                saved_path = await save_generated_image(
                    generated_image,
                    download_dir,
                    f"gemini_web_image_{stamp}_{index}",
                    download_timeout,
                    full_size=image_full_size,
                )
                item_result: dict[str, object] = {
                    "type": "image",
                    "path": saved_path,
                    "full_size": image_full_size,
                }
                if remove_watermarks:
                    item_result.update(
                        cleanup_generated_file(
                            saved_path,
                            output_dir,
                            "image",
                            keep_originals,
                            image_backend,
                        )
                    )
                saved.append(item_result)
        else:
            for index, video in enumerate(response.videos, start=1):
                downloaded = await save_generated_video(
                    video,
                    download_dir,
                    f"gemini_web_video_{stamp}_{index}",
                    download_timeout,
                )
                item_result = {"type": "video", **downloaded}
                if remove_watermarks and downloaded.get("video"):
                    video_cleanup = cleanup_generated_file(
                        str(downloaded["video"]),
                        output_dir,
                        "video",
                        keep_originals,
                        image_backend,
                    )
                    item_result["video"] = video_cleanup.pop("path")
                    item_result["watermark_cleanup"] = video_cleanup
                if remove_watermarks and downloaded.get("video_thumbnail"):
                    thumbnail_cleanup = cleanup_generated_file(
                        str(downloaded["video_thumbnail"]),
                        output_dir,
                        "image",
                        keep_originals,
                        image_backend,
                    )
                    item_result["video_thumbnail"] = thumbnail_cleanup.pop("path")
                    item_result["thumbnail_watermark_cleanup"] = thumbnail_cleanup
                saved.append(item_result)

            for index, media_item in enumerate(response.media, start=1):
                if getattr(media_item, "url", ""):
                    downloaded = await save_generated_video(
                        media_item,
                        download_dir,
                        f"gemini_web_media_{stamp}_{index}",
                        download_timeout,
                        media=True,
                    )
                    item_result = {"type": "video", **downloaded}
                    if remove_watermarks and downloaded.get("video"):
                        video_cleanup = cleanup_generated_file(
                            str(downloaded["video"]),
                            output_dir,
                            "video",
                            keep_originals,
                            image_backend,
                        )
                        item_result["video"] = video_cleanup.pop("path")
                        item_result["watermark_cleanup"] = video_cleanup
                    if remove_watermarks and downloaded.get("video_thumbnail"):
                        thumbnail_cleanup = cleanup_generated_file(
                            str(downloaded["video_thumbnail"]),
                            output_dir,
                            "image",
                            keep_originals,
                            image_backend,
                        )
                        item_result["video_thumbnail"] = thumbnail_cleanup.pop("path")
                        item_result["thumbnail_watermark_cleanup"] = thumbnail_cleanup
                    saved.append(item_result)

        if remove_watermarks:
            try:
                staging_dir.rmdir()
                staging_dir.parent.rmdir()
            except OSError:
                pass

        result["saved"] = saved
        if saved:
            result["status"] = "complete"
        elif should_redo_image(response.text):
            result["status"] = "quota_exhausted"
        else:
            result["status"] = f"no_{media_type}_returned"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_result(output_dir, result)

        if not saved:
            print(
                f"Gemini returned no downloadable {media_type}: {result['status']}.",
                flush=True,
            )
            return 3

        print(json.dumps({"saved": saved}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        result["status"] = "error"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_result(output_dir, result)
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
