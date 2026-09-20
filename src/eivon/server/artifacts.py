"""Private artifact storage and authorized downloads."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import select

from .db import Artifact, Database, row_dict, uid
from .errors import ServiceError
from .security import Principal
from .settings import Settings


class Artifacts:
    def __init__(self, database: Database, settings: Settings):
        self.database, self.settings = database, settings
        self.directory = settings.data_dir / "artifacts"
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        workspace_id: str,
        user_id: str,
        run_id: str | None,
        name: str,
        media_type: str,
        content: bytes,
    ) -> dict:
        if len(content) > self.settings.max_upload_bytes:
            raise ServiceError("file_too_large", "File exceeds the configured upload limit", 413)
        safe_name = re.sub(r"[^\w. -]", "_", name, flags=re.UNICODE).strip(" .")[:180] or "artifact"
        artifact_id = uid()
        path = self.directory / artifact_id
        path.write_bytes(content)
        try:
            with self.database.transaction() as db:
                artifact = Artifact(
                    id=artifact_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    run_id=run_id,
                    name=safe_name,
                    media_type=media_type,
                    size=len(content),
                    digest=hashlib.sha256(content).hexdigest(),
                )
                db.add(artifact)
                db.flush()
                return {**row_dict(artifact), "url": f"/api/v1/artifacts/{artifact_id}/download"}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def get(self, principal: Principal, artifact_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            artifact = db.get(Artifact, artifact_id)
            if (
                artifact is None
                or artifact.workspace_id != principal.workspace_id
                or (artifact.user_id != principal.user_id and "admin" not in principal.permissions)
            ):
                raise ServiceError("not_found", "Artifact not found", 404)
            return row_dict(artifact)

    def for_run(self, principal: Principal, run_id: str) -> list[dict]:
        principal.require("read")
        filters = [Artifact.workspace_id == principal.workspace_id, Artifact.run_id == run_id]
        if "admin" not in principal.permissions:
            filters.append(Artifact.user_id == principal.user_id)
        with self.database.transaction() as db:
            return [
                row_dict(item)
                for item in db.scalars(
                    select(Artifact).where(*filters).order_by(Artifact.created_at, Artifact.id)
                )
            ]
