"""API tokens, for the CLI."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from paritylens_api.core.errors import NotFoundError
from paritylens_api.core.security import hash_token, new_api_token
from paritylens_api.deps import BrowserPrincipalDep, SessionDep
from paritylens_api.models import ApiToken
from paritylens_api.schemas.auth import ApiTokenCreate, ApiTokenCreated, ApiTokenOut

router = APIRouter(tags=["api tokens"])


@router.get("/api-tokens")
async def list_tokens(principal: BrowserPrincipalDep, session: SessionDep) -> list[ApiTokenOut]:
    rows = await session.scalars(
        select(ApiToken)
        .where(ApiToken.workspace_id == principal.workspace_id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at)
    )
    return [ApiTokenOut.model_validate(row) for row in rows]


@router.post("/api-tokens", status_code=201)
async def create_token(
    body: ApiTokenCreate, principal: BrowserPrincipalDep, session: SessionDep
) -> ApiTokenCreated:
    token = new_api_token()
    row = ApiToken(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        name=body.name,
        token_hash=hash_token(token),
        token_hint=token[:8],
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    # The only response that ever contains the token itself.
    return ApiTokenCreated(**ApiTokenOut.model_validate(row).model_dump(), token=token)


@router.delete("/api-tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID, principal: BrowserPrincipalDep, session: SessionDep
) -> None:
    row = await session.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.workspace_id == principal.workspace_id,
            ApiToken.revoked_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundError("API token not found")
    row.revoked_at = datetime.now(UTC)
