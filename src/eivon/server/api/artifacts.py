from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from .dependencies import Identity

router = APIRouter()


@router.get("/artifacts/{artifact_id}")
def artifact(artifact_id: str, request: Request, identity: Identity):
    return request.app.state.artifacts.get(identity, artifact_id)


@router.get("/artifacts/{artifact_id}/download")
def download(artifact_id: str, request: Request, identity: Identity):
    item = request.app.state.artifacts.get(identity, artifact_id)
    path = request.app.state.artifacts.directory / artifact_id
    if not path.is_file():
        from ..errors import ServiceError

        raise ServiceError("not_found", "Artifact content not found", 404)
    return FileResponse(
        path,
        media_type=item["media_type"],
        filename=item["name"],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{item['name']}"},
    )
