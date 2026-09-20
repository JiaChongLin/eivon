"""Authenticated API dependencies; workspace and permissions are server-derived."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request

from ..errors import ServiceError
from ..security import Principal


def principal(request: Request) -> Principal:
    security = request.app.state.security
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, raw = authorization.partition(" ")
        if scheme.lower() != "bearer" or not raw:
            raise ServiceError("unauthorized", "Expected a bearer API key", 401)
        return security.authenticate(raw, request.headers.get("x-eivon-workspace"), bearer=True)
    token = request.cookies.get("eivon_session", "")
    if not token:
        raise ServiceError("unauthorized", "Sign in to continue", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), security.csrf(token)):
            raise ServiceError("csrf_failed", "Refresh the page and try again", 403)
    return security.authenticate(token, request.headers.get("x-eivon-workspace"))


Identity = Annotated[Principal, Depends(principal)]
