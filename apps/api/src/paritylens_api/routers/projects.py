"""Projects and everything configured on them: endpoints, rules, secrets, test cases."""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from paritylens_api.core.crypto import secret_context
from paritylens_api.core.errors import ConflictError, InvalidRequestError
from paritylens_api.deps import PrincipalDep, SecretBoxDep, SessionDep, SettingsDep
from paritylens_api.models import Endpoint, Project, Rule, Secret, TestCase
from paritylens_api.repositories.owned import get_child, get_project, list_children
from paritylens_api.schemas.projects import (
    EndpointCreate,
    EndpointOut,
    OpenApiImport,
    OpenApiImportResult,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    RuleCreate,
    RuleOut,
    SecretName,
    SecretOut,
    SecretPut,
    TestCaseOut,
    TestCaseWrite,
)
from paritylens_api.services import openapi_import
from paritylens_api.services.egress import check_targets

router = APIRouter()


def _project_out(project: Project) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.has_openapi_spec = project.openapi_spec is not None
    return out


# --- projects --------------------------------------------------------------------


@router.get("/projects", tags=["projects"])
async def list_projects(principal: PrincipalDep, session: SessionDep) -> list[ProjectOut]:
    rows = await session.scalars(
        select(Project)
        .where(Project.workspace_id == principal.workspace_id)
        .order_by(Project.created_at.desc())
    )
    return [_project_out(row) for row in rows]


@router.post("/projects", status_code=201, tags=["projects"])
async def create_project(
    body: ProjectCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> ProjectOut:
    check_targets(settings, body.old_base_url, body.new_base_url)
    project = Project(workspace_id=principal.workspace_id, **body.model_dump())
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return _project_out(project)


@router.get("/projects/{project_id}", tags=["projects"])
async def read_project(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> ProjectOut:
    return _project_out(await get_project(session, principal.workspace_id, project_id))


@router.patch("/projects/{project_id}", tags=["projects"])
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ProjectOut:
    project = await get_project(session, principal.workspace_id, project_id)
    check_targets(settings, body.old_base_url, body.new_base_url)
    # exclude_unset: only what the client actually sent. A field left out
    # is unchanged; that is different from a field sent as null.
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, field, value)
    await session.flush()
    await session.refresh(project)
    return _project_out(project)


@router.delete("/projects/{project_id}", status_code=204, tags=["projects"])
async def delete_project(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await session.delete(await get_project(session, principal.workspace_id, project_id))


# --- endpoints -------------------------------------------------------------------


@router.get("/projects/{project_id}/endpoints", tags=["endpoints"])
async def list_endpoints(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[EndpointOut]:
    rows = await list_children(session, Endpoint, principal.workspace_id, project_id)
    return [EndpointOut.model_validate(row) for row in rows]


@router.post("/projects/{project_id}/endpoints", status_code=201, tags=["endpoints"])
async def create_endpoint(
    project_id: uuid.UUID, body: EndpointCreate, principal: PrincipalDep, session: SessionDep
) -> EndpointOut:
    project = await get_project(session, principal.workspace_id, project_id)
    endpoint = Endpoint(project_id=project.id, source="manual", **body.model_dump())
    session.add(endpoint)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("this method and path are already registered") from exc
    await session.refresh(endpoint)
    return EndpointOut.model_validate(endpoint)


@router.delete("/endpoints/{endpoint_id}", status_code=204, tags=["endpoints"])
async def delete_endpoint(
    endpoint_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await session.delete(await get_child(session, Endpoint, principal.workspace_id, endpoint_id))


@router.post("/projects/{project_id}/openapi", tags=["endpoints"])
async def import_openapi(
    project_id: uuid.UUID, body: OpenApiImport, principal: PrincipalDep, session: SessionDep
) -> OpenApiImportResult:
    """Store an OpenAPI document and register every operation in it as an endpoint."""
    project = await get_project(session, principal.workspace_id, project_id)
    # storable() first: everything after it works on plain, bounded JSON.
    document = openapi_import.storable(openapi_import.parse_document(body.document))
    found = openapi_import.endpoints_in(document)
    project.openapi_spec = document

    created = 0
    for endpoint in found:
        # ON CONFLICT DO NOTHING: importing the same document twice, or one
        # that overlaps manual entries, adds only what is new.
        result = await session.execute(
            insert(Endpoint)
            .values(
                id=uuid.uuid4(),
                project_id=project.id,
                method=endpoint.method,
                path_template=endpoint.path_template,
                summary=endpoint.summary,
                source="openapi",
            )
            .on_conflict_do_nothing(index_elements=["project_id", "method", "path_template"])
            .returning(Endpoint.id)
        )
        created += len(result.all())
    rows = await list_children(session, Endpoint, principal.workspace_id, project_id)
    return OpenApiImportResult(
        created=created,
        already_present=len(found) - created,
        endpoints=[EndpointOut.model_validate(row) for row in rows],
    )


# --- rules -----------------------------------------------------------------------


@router.get("/projects/{project_id}/rules", tags=["rules"])
async def list_rules(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[RuleOut]:
    rows = await list_children(session, Rule, principal.workspace_id, project_id)
    return [RuleOut.model_validate(row) for row in rows]


@router.post("/projects/{project_id}/rules", status_code=201, tags=["rules"])
async def create_rule(
    project_id: uuid.UUID, body: RuleCreate, principal: PrincipalDep, session: SessionDep
) -> RuleOut:
    project = await get_project(session, principal.workspace_id, project_id)
    rule = Rule(
        project_id=project.id,
        kind=body.kind,
        path=body.path.lower() if body.kind == "compare_header" else body.path,
        options={"key": body.key} if body.key else {},
    )
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    return RuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204, tags=["rules"])
async def delete_rule(rule_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await session.delete(await get_child(session, Rule, principal.workspace_id, rule_id))


# --- secrets ---------------------------------------------------------------------


@router.get("/projects/{project_id}/secrets", tags=["secrets"])
async def list_secrets(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[SecretOut]:
    """Names only. No endpoint returns a secret's value."""
    rows = await list_children(session, Secret, principal.workspace_id, project_id)
    return [SecretOut.model_validate(row) for row in rows]


@router.put("/projects/{project_id}/secrets/{name}", tags=["secrets"])
async def put_secret(
    project_id: uuid.UUID,
    name: SecretName,
    body: SecretPut,
    principal: PrincipalDep,
    session: SessionDep,
    box: SecretBoxDep,
) -> SecretOut:
    project = await get_project(session, principal.workspace_id, project_id)
    encrypted = box.encrypt(body.value, context=secret_context(project.id, name))
    # One statement that inserts or replaces. Looking first and inserting
    # second would fail when two requests set the same secret at once.
    values = {
        "ciphertext": encrypted.ciphertext,
        "nonce": encrypted.nonce,
        "key_version": encrypted.key_version,
    }
    row = await session.scalar(
        insert(Secret)
        .values(id=uuid.uuid4(), project_id=project.id, name=name, **values)
        .on_conflict_do_update(
            index_elements=["project_id", "name"],
            set_={**values, "updated_at": func.clock_timestamp()},
        )
        .returning(Secret)
    )
    return SecretOut.model_validate(row)


@router.delete("/projects/{project_id}/secrets/{name}", status_code=204, tags=["secrets"])
async def delete_secret(
    project_id: uuid.UUID, name: SecretName, principal: PrincipalDep, session: SessionDep
) -> None:
    project = await get_project(session, principal.workspace_id, project_id)
    row = await session.scalar(
        select(Secret).where(Secret.project_id == project.id, Secret.name == name)
    )
    if row is not None:
        await session.delete(row)


# --- test cases ------------------------------------------------------------------


@router.get("/projects/{project_id}/test-cases", tags=["test cases"])
async def list_test_cases(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[TestCaseOut]:
    rows = await list_children(session, TestCase, principal.workspace_id, project_id)
    return [TestCaseOut.model_validate(row) for row in rows]


async def _owned_endpoint_id(
    session: SessionDep, workspace_id: uuid.UUID, project_id: uuid.UUID, body: TestCaseWrite
) -> uuid.UUID | None:
    if body.endpoint_id is None:
        return None
    # The endpoint must be the caller's too, and in the same project.
    endpoint = await get_child(session, Endpoint, workspace_id, body.endpoint_id)
    if endpoint.project_id != project_id:
        raise InvalidRequestError("the endpoint belongs to a different project")
    return endpoint.id


@router.post("/projects/{project_id}/test-cases", status_code=201, tags=["test cases"])
async def create_test_case(
    project_id: uuid.UUID, body: TestCaseWrite, principal: PrincipalDep, session: SessionDep
) -> TestCaseOut:
    project = await get_project(session, principal.workspace_id, project_id)
    case = TestCase(
        project_id=project.id,
        endpoint_id=await _owned_endpoint_id(session, principal.workspace_id, project.id, body),
        name=body.name,
        steps=body.steps_as_json(),
        noise_detection=body.noise_detection,
        enabled=body.enabled,
    )
    session.add(case)
    await session.flush()
    await session.refresh(case)
    return TestCaseOut.model_validate(case)


@router.get("/test-cases/{test_case_id}", tags=["test cases"])
async def read_test_case(
    test_case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> TestCaseOut:
    case = await get_child(session, TestCase, principal.workspace_id, test_case_id)
    return TestCaseOut.model_validate(case)


@router.put("/test-cases/{test_case_id}", tags=["test cases"])
async def replace_test_case(
    test_case_id: uuid.UUID, body: TestCaseWrite, principal: PrincipalDep, session: SessionDep
) -> TestCaseOut:
    case = await get_child(session, TestCase, principal.workspace_id, test_case_id)
    case.endpoint_id = await _owned_endpoint_id(
        session, principal.workspace_id, case.project_id, body
    )
    case.name = body.name
    case.steps = body.steps_as_json()
    case.noise_detection = body.noise_detection
    case.enabled = body.enabled
    await session.flush()
    await session.refresh(case)
    return TestCaseOut.model_validate(case)


@router.delete("/test-cases/{test_case_id}", status_code=204, tags=["test cases"])
async def delete_test_case(
    test_case_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await session.delete(await get_child(session, TestCase, principal.workspace_id, test_case_id))
