"""Tenant isolation, in one place.

Every lookup of a user-owned row goes through these functions, and each
takes the caller's workspace_id. There is deliberately no function here
that fetches by ID alone: a handler cannot forget the workspace check
because there is nothing to call that skips it.

A row in another workspace is reported exactly like a row that does not
exist. Saying "forbidden" instead would confirm that the ID is real.
"""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from paritylens_api.core.errors import NotFoundError
from paritylens_api.models import (
    CaseResult,
    Endpoint,
    Project,
    Rule,
    Run,
    Secret,
    TestCase,
)

# Tables that belong to a project directly.
type ProjectChild = Endpoint | Rule | Secret | TestCase | Run


async def get_project(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None:
        raise NotFoundError("project not found")
    return project


def in_workspace[T: ProjectChild](model: type[T], workspace_id: uuid.UUID) -> Select[T]:
    """A query for rows of `model` whose project is in the workspace."""
    return (
        select(model)
        .join(Project, model.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    )


async def get_child[T: ProjectChild](
    session: AsyncSession, model: type[T], workspace_id: uuid.UUID, row_id: uuid.UUID
) -> T:
    row = await session.scalar(in_workspace(model, workspace_id).where(model.id == row_id))
    if row is None:
        raise NotFoundError(f"{model.__tablename__.rstrip('s').replace('_', ' ')} not found")
    return row


async def list_children[T: ProjectChild](
    session: AsyncSession, model: type[T], workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[T]:
    # get_project first: an unknown or foreign project is a 404, not an empty list.
    await get_project(session, workspace_id, project_id)
    order: Any = model.created_at
    rows = await session.scalars(
        select(model).where(model.project_id == project_id).order_by(order, model.id)
    )
    return list(rows)


async def get_case_result(
    session: AsyncSession, workspace_id: uuid.UUID, case_result_id: uuid.UUID
) -> CaseResult:
    row = await session.scalar(
        select(CaseResult)
        .join(Run, CaseResult.run_id == Run.id)
        .join(Project, Run.project_id == Project.id)
        .where(CaseResult.id == case_result_id, Project.workspace_id == workspace_id)
    )
    if row is None:
        raise NotFoundError("case result not found")
    return row
