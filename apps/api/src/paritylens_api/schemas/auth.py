import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from paritylens_api.core.config import AuthMode
from paritylens_api.schemas.common import ApiModel, RequestModel


class AuthConfig(ApiModel):
    mode: AuthMode


class DevLogin(RequestModel):
    email: EmailStr


class Me(ApiModel):
    user_id: uuid.UUID
    email: str
    name: str
    workspace_id: uuid.UUID
    workspace_name: str


class ApiTokenCreate(RequestModel):
    name: str = Field(min_length=1, max_length=100)


class ApiTokenOut(ApiModel):
    id: uuid.UUID
    name: str
    token_hint: str
    last_used_at: datetime | None
    created_at: datetime


class ApiTokenCreated(ApiTokenOut):
    # Shown once, at creation. Only its hash is stored.
    token: str
