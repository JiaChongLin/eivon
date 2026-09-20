from fastapi import APIRouter, Request

from .dependencies import Identity

router = APIRouter()


@router.get("/extensions")
def extensions(request: Request):
    return {"items": request.app.state.extensions.packages}


@router.get("/stats")
def stats(request: Request, identity: Identity):
    from sqlalchemy import func, select

    from ..db import Resource, Run

    with request.app.state.database.transaction() as db:
        resources = db.scalar(
            select(func.count())
            .select_from(Resource)
            .where(Resource.workspace_id == identity.workspace_id, Resource.archived.is_(False))
        )
        runs = db.scalar(
            select(func.count()).select_from(Run).where(Run.workspace_id == identity.workspace_id)
        )
    return {"name": "Eivon", "version": "0.1.0", "resources": resources, "runs": runs}
