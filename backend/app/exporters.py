from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from build_xlsx_portable import write_workbook


@dataclass(frozen=True)
class ExportContext:
    run_id: str
    filename_stem: str
    revision_number: int | None = None


@dataclass(frozen=True)
class ExportedFile:
    filename: str
    media_type: str
    content: bytes


class DocumentExporter(Protocol):
    kind: str

    def export(self, document: dict[str, Any], context: ExportContext) -> ExportedFile:
        """Convert a generic structured document into one output format."""


class JsonDocumentExporter:
    kind = "json"

    def export(self, document: dict[str, Any], context: ExportContext) -> ExportedFile:
        content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        filename = f"revision-{context.revision_number:03d}.json" if context.revision_number is not None else f"{context.filename_stem}.json"
        return ExportedFile(filename, "application/json", content)


class XlsxDocumentExporter:
    kind = "xlsx"

    def export(self, document: dict[str, Any], context: ExportContext) -> ExportedFile:
        filename = f"revision-{context.revision_number:03d}.xlsx" if context.revision_number is not None else f"{context.filename_stem}.xlsx"
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            temporary_path = Path(handle.name)
        try:
            write_workbook(document, temporary_path)
            return ExportedFile(filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", temporary_path.read_bytes())
        finally:
            temporary_path.unlink(missing_ok=True)


class ExporterRegistry:
    """Small explicit registry; future database sinks can join this seam."""

    def __init__(self, exporters: list[DocumentExporter] | None = None):
        self._exporters = {exporter.kind: exporter for exporter in (exporters or [JsonDocumentExporter(), XlsxDocumentExporter()])}

    def get(self, kind: str) -> DocumentExporter:
        try:
            return self._exporters[kind]
        except KeyError as error:
            raise ValueError(f"unsupported export format: {kind}") from error
