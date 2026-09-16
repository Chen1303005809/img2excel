from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from .models import Artifact


@dataclass(frozen=True)
class StoredArtifact:
    id: str
    relative_path: str
    absolute_path: Path
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


class ArtifactStore:
    """Owns safe, run-scoped filesystem storage for pipeline artifacts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        path = (self.root / "runs" / run_id).resolve()
        path.relative_to(self.root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write(self, run_id: str, relative_path: str, content: bytes) -> StoredArtifact:
        destination = (self.root / "runs" / run_id / relative_path).resolve()
        destination.relative_to(self.root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        temporary.write_bytes(content)
        temporary.replace(destination)
        digest = hashlib.sha256(content).hexdigest()
        media_type = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
        return StoredArtifact(
            id=str(uuid4()),
            relative_path=str(destination.relative_to(self.root)),
            absolute_path=destination,
            filename=destination.name,
            media_type=media_type,
            size_bytes=len(content),
            sha256=digest,
        )

    def write_bytes(self, run_id: str, relative_path: str, content: bytes, media_type: str | None = None) -> StoredArtifact:
        artifact = self._write(run_id, relative_path, content)
        if media_type:
            artifact = StoredArtifact(
                id=artifact.id,
                relative_path=artifact.relative_path,
                absolute_path=artifact.absolute_path,
                filename=artifact.filename,
                media_type=media_type,
                size_bytes=artifact.size_bytes,
                sha256=artifact.sha256,
            )
        return artifact

    def write_json(self, run_id: str, relative_path: str, payload: dict[str, Any]) -> StoredArtifact:
        content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        return self.write_bytes(run_id, relative_path, content, "application/json")

    def absolute_path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        path.relative_to(self.root)
        return path


def record_artifact(session: Session, run_id: str, stored: StoredArtifact, kind: str, revision_id: str | None = None) -> Artifact:
    revision_filter = Artifact.revision_id.is_(None) if revision_id is None else Artifact.revision_id == revision_id
    existing = session.scalar(
        select(Artifact)
        .where(and_(Artifact.run_id == run_id, Artifact.kind == kind, revision_filter, Artifact.relative_path == stored.relative_path))
        .limit(1)
    )
    if existing is not None:
        # Retries may atomically replace the same run-scoped file. Keep one
        # database record and refresh its integrity metadata instead of
        # accumulating duplicate artifact rows after a Worker restart.
        existing.media_type = stored.media_type
        existing.filename = stored.filename
        existing.size_bytes = stored.size_bytes
        existing.sha256 = stored.sha256
        session.commit()
        return existing
    record = Artifact(
        id=stored.id,
        run_id=run_id,
        revision_id=revision_id,
        kind=kind,
        relative_path=stored.relative_path,
        media_type=stored.media_type,
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    session.add(record)
    session.commit()
    return record
