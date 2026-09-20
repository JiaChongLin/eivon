from fastapi import APIRouter, Query, Request

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


@router.get("/audit-events")
def audit_events(
    request: Request,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
):
    from sqlalchemy import func, select

    from ..db import AuditEvent, row_dict

    identity.require("admin")
    with request.app.state.database.transaction() as db:
        filters = [AuditEvent.workspace_id == identity.workspace_id]
        total = db.scalar(select(func.count()).select_from(AuditEvent).where(*filters))
        rows = db.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset(offset)
            .limit(limit)
        )
        return {"items": [row_dict(row) for row in rows], "total": total}
