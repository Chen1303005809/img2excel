#!/usr/bin/env python3
"""One-command portable image-to-XLSX CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from build_xlsx_portable import write_workbook
from image_to_rows import extract


IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".jfif", ".png", ".tif", ".tiff", ".webp"})


def find_images(input_dir: Path, recursive: bool = False) -> list[Path]:
    """Return supported images in deterministic order."""
    candidates: Iterable[Path] = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(
        (path for path in candidates if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
        key=lambda path: path.as_posix().casefold(),
    )


def batch_output_paths(images: list[Path], output_dir: Path) -> dict[Path, Path]:
    """Map each source image to a same-stem XLSX path and reject collisions."""
    paths = {image: output_dir / f"{image.stem}.xlsx" for image in images}
    by_target: dict[str, list[Path]] = {}
    for image, target in paths.items():
        # Case-folding also catches collisions on case-insensitive filesystems.
        by_target.setdefault(target.name.casefold(), []).append(image)
    collisions = [sources for sources in by_target.values() if len(sources) > 1]
    if collisions:
        details = "; ".join(", ".join(str(source) for source in sources) for sources in collisions)
        raise ValueError(f"duplicate output filenames in batch: {details}")
    return paths


def json_path_for(image: Path, json_output: Path | None, batch: bool) -> Path | None:
    if json_output is None:
        return None
    return json_output / f"{image.stem}.json" if batch else json_output


def convert_one(image: Path, output: Path, json_output: Path | None = None) -> None:
    data = extract(image)
    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_workbook(data, output)
    print(json.dumps(data["metrics"], ensure_ascii=False))
    print(f"XLSX_SAVED {output}")


def run_batch(images: list[Path], output_dir: Path, json_dir: Path | None = None) -> int:
    targets = batch_output_paths(images, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if json_dir:
        json_dir.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[Path, str]] = []
    for image in images:
        output = targets[image]
        try:
            convert_one(image, output, json_path_for(image, json_dir, batch=True))
        except (Exception, SystemExit) as error:
            message = str(error)
            if not message:
                message = f"exit code {error.code}" if isinstance(error, SystemExit) else error.__class__.__name__
            failures.append((image, message))
            print(f"FAILED {image}: {message}", file=sys.stderr)

    succeeded = len(images) - len(failures)
    print(f"BATCH_DONE total={len(images)} succeeded={succeeded} failed={len(failures)}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert one table image or all supported images in a directory to XLSX."
    )
    parser.add_argument("input", type=Path, help="input image path or directory")
    parser.add_argument(
        "output",
        type=Path,
        help="output .xlsx path for one image, or output directory for a directory input",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="audit JSON path for one image, or JSON directory for a directory input",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="when input is a directory, also scan images in nested directories",
    )
    args = parser.parse_args()

    if args.input.is_dir():
        images = find_images(args.input, recursive=args.recursive)
        if not images:
            scope = "directory and its subdirectories" if args.recursive else "directory"
            parser.error(f"no supported images found in {scope}: {args.input}")
        raise SystemExit(run_batch(images, args.output, args.json_output))

    if not args.input.is_file():
        parser.error(f"input path does not exist or is not a file/directory: {args.input}")
    if args.recursive:
        parser.error("--recursive can only be used when input is a directory")

    convert_one(args.input, args.output, args.json_output)


if __name__ == "__main__":
    main()
