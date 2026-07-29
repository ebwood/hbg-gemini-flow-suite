from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


REMOVE_AI_WATERMARKS = "/opt/gemini-venv/bin/remove-ai-watermarks"
VEO_WATERMARK_REMOVER = "/usr/local/bin/veo-watermark-remover"


def run_checked(command: list[str]) -> None:
    print(f"Running media cleanup: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def clean_image(source: Path, output: Path, backend: str = "migan") -> Path:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        REMOVE_AI_WATERMARKS,
        "visible",
        str(source),
        "--detect",
        "--mark",
        "auto",
        "--sensitivity",
        "auto",
        "--backend",
        backend,
        "--strip-metadata",
        "--output",
        str(output),
    ]
    print(f"Running media cleanup: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", flush=True)

    combined_output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 2 and "No known visible mark detected" in combined_output:
        # Exit code 2 means detection found nothing to inpaint. This is a valid
        # Flow image result, so still strip provenance/EXIF metadata and deliver it.
        run_checked(
            [
                REMOVE_AI_WATERMARKS,
                "metadata",
                str(source),
                "--remove",
                "--output",
                str(output),
            ]
        )
    elif completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command)
    if not output.is_file():
        raise RuntimeError(f"Image cleanup produced no output: {output}")
    return output


def clean_video(source: Path, output: Path) -> Path:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    visible_clean = output.parent / f".{output.stem}.visible-clean{output.suffix}"
    diamond_clean = output.parent / f".{output.stem}.diamond-clean{output.suffix}"

    try:
        run_checked(
            [
                VEO_WATERMARK_REMOVER,
                "--no-banner",
                "--veo",
                "--mark",
                "auto",
                "--input",
                str(source),
                "--output",
                str(visible_clean),
            ]
        )
        if not visible_clean.is_file():
            raise RuntimeError(
                f"Visible video watermark cleanup produced no output: {visible_clean}"
            )

        metadata_source = visible_clean
        if "gemini_web_video" in source.name:
            # Gemini Web's 3.5 diamond can move farther inward than the stable
            # auto profile expects. A second bottom-right snap pass catches the
            # residual mark that can otherwise survive while the first pass
            # still reports success.
            run_checked(
                [
                    VEO_WATERMARK_REMOVER,
                    "--no-banner",
                    "--veo",
                    "--mark",
                    "diamond",
                    "--force",
                    "--region",
                    "br:auto",
                    "--snap",
                    "--denoise",
                    "ai",
                    "--input",
                    str(visible_clean),
                    "--output",
                    str(diamond_clean),
                ]
            )
            if not diamond_clean.is_file():
                raise RuntimeError(
                    f"Gemini diamond second pass produced no output: {diamond_clean}"
                )
            metadata_source = diamond_clean

        run_checked(
            [
                REMOVE_AI_WATERMARKS,
                "metadata",
                str(metadata_source),
                "--remove",
                "--output",
                str(output),
            ]
        )
        if not output.is_file():
            raise RuntimeError(f"Video metadata cleanup produced no output: {output}")
        return output
    finally:
        visible_clean.unlink(missing_ok=True)
        diamond_clean.unlink(missing_ok=True)


def clean_media(source: Path, output: Path, media_type: str, backend: str = "migan") -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Generated media does not exist: {source}")
    if media_type == "image":
        return clean_image(source, output, backend=backend)
    if media_type == "video":
        return clean_video(source, output)
    raise ValueError(f"Unsupported media type: {media_type}")


def retain_or_remove_original(source: Path, output_dir: Path, keep_original: bool) -> str | None:
    if keep_original:
        original_dir = output_dir / ".originals"
        original_dir.mkdir(parents=True, exist_ok=True)
        destination = original_dir / source.name
        shutil.move(str(source), str(destination))
        return str(destination)
    source.unlink(missing_ok=True)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove visible Gemini/Veo marks and provenance metadata."
    )
    parser.add_argument("media_type", choices=("image", "video"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--backend",
        default=os.environ.get("IMAGE_CLEAN_BACKEND", "migan"),
        choices=("auto", "cv2", "migan", "lama"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = clean_media(args.source, args.output, args.media_type, args.backend)
    print(result, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
