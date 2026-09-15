#!/usr/bin/env python3
"""One-command portable image-to-XLSX CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_xlsx_portable import write_workbook
from image_to_rows import extract


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a table image to XLSX with adaptive local OCR.")
    parser.add_argument("image", type=Path, help="input image path")
    parser.add_argument("output", type=Path, help="output .xlsx path")
    parser.add_argument("--json-output", type=Path, help="optional intermediate JSON path for audit/debugging")
    args = parser.parse_args()

    data = extract(args.image)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_workbook(data, args.output)
    print(json.dumps(data["metrics"], ensure_ascii=False))
    print(f"XLSX_SAVED {args.output}")


if __name__ == "__main__":
    main()
