"""Several workers on one queue: no run is taken twice.

Unlike the other tests this one cannot live inside a single rolled-back
transaction, because the point is what happens between separate
connections. It commits its rows for real and deletes them afterwards.
"""

import asyncio
import uuid

import pytest
from paritylens_api.models import Project, Run, Workspace
from paritylens_api.worker.loop import claim_next_run
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.anyio


async def test_concurrent_workers_each_claim_a_different_run(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_size=8)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id = uuid.uuid4()
    try:
        async with sessions() as session, session.begin():
            session.add(Workspace(id=workspace_id, name="concurrency test"))
            # The models declare no relationship between these two tables,
            # so the ORM cannot work out which INSERT must come first.
            await session.flush()
            project = Project(
                workspace_id=workspace_id,
                name="p",
                old_base_url="http://old.test",
                new_base_url="http://new.test",
            )
            session.add(project)
            await session.flush()
            for _ in range(3):
                session.add(
                    Run(
                        project_id=project.id,
                        source="hosted",
                        status="queued",
                        old_base_url="http://old.test",
                        new_base_url="http://new.test",
                    )
                )

        # Six workers reach for three runs at the same moment.
        claimed = await asyncio.gather(*(claim_next_run(sessions) for _ in range(6)))

        taken = [run_id for run_id in claimed if run_id is not None]
        assert len(taken) == 3
        assert len(set(taken)) == 3
        async with sessions() as session:
            statuses = (await session.scalars(select(Run.status))).all()
        assert set(statuses) == {"running"}
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await engine.dispose()
