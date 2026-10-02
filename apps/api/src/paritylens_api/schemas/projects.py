import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from paritylens_engine.model import RuleSet, UnorderedRule
from paritylens_engine.suite import Case, HttpMethod, Step, Target
from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from paritylens_api.schemas.common import ApiModel, RequestModel

# In stored headers, a credential is referred to by name: {{secret.SHOP_TOKEN}}.
SECRET_REFERENCE = re.compile(r"\{\{\s*secret\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

type SecretName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100)]


def _valid_target(base_url: str) -> str:
    # The engine's own check, so the API accepts exactly what a run accepts.
    return Target(base_url=base_url).base_url


def _valid_headers(headers: dict[str, str]) -> dict[str, str]:
    Target(base_url="http://placeholder.invalid", headers=headers)
    return headers


type BaseUrl = Annotated[str, Field(max_length=2000), AfterValidator(_valid_target)]
type TargetHeaders = Annotated[dict[str, str], Field(max_length=50), AfterValidator(_valid_headers)]


class ProjectCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    old_base_url: BaseUrl
    new_base_url: BaseUrl
    old_headers: TargetHeaders = Field(default_factory=dict)
    new_headers: TargetHeaders = Field(default_factory=dict)
    critical_field_names: bool = True
    ai_enabled: bool = False


class ProjectUpdate(RequestModel):
    """Only the fields that are sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    old_base_url: BaseUrl | None = None
    new_base_url: BaseUrl | None = None
    old_headers: TargetHeaders | None = None
    new_headers: TargetHeaders | None = None
    critical_field_names: bool | None = None
    ai_enabled: bool | None = None


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    old_base_url: str
    new_base_url: str
    old_headers: dict[str, str]
    new_headers: dict[str, str]
    critical_field_names: bool
    ai_enabled: bool
    has_openapi_spec: bool = False
    created_at: datetime
    updated_at: datetime


def _uppercase(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


# The (project, method, path) uniqueness index cannot hold a very long
# path. The limit is in bytes because that is what the index counts.
MAX_PATH_TEMPLATE_BYTES = 1024


def _indexable_path(path: str) -> str:
    if len(path.encode("utf-8")) > MAX_PATH_TEMPLATE_BYTES:
        raise ValueError(f"path_template may be at most {MAX_PATH_TEMPLATE_BYTES} bytes")
    return path


class EndpointCreate(RequestModel):
    method: Annotated[HttpMethod, BeforeValidator(_uppercase)]
    path_template: Annotated[
        str, Field(min_length=1, pattern=r"^/"), AfterValidator(_indexable_path)
    ]
    summary: str = Field(default="", max_length=500)


class EndpointOut(ApiModel):
    id: uuid.UUID
    method: str
    path_template: str
    summary: str
    source: str
    created_at: datetime


class OpenApiImport(RequestModel):
    # The document as text, JSON or YAML.
    document: str = Field(min_length=1, max_length=1024 * 1024)


class OpenApiImportResult(ApiModel):
    created: int
    already_present: int
    endpoints: list[EndpointOut]


RuleKind = Literal["ignore", "unordered", "critical", "compare_header"]


class RuleCreate(RequestModel):
    kind: RuleKind
    # A path pattern, or a header name when kind is compare_header.
    path: str = Field(min_length=1, max_length=1000)
    # unordered only: the field that identifies an element.
    key: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _is_a_rule_the_engine_accepts(self) -> Self:
        if self.key is not None and self.kind != "unordered":
            raise ValueError("'key' only applies to unordered rules")
        # Build the engine's own model, so a rule that is saved is a rule
        # that will load when a run starts.
        match self.kind:
            case "ignore":
                RuleSet(ignore=(self.path,))
            case "critical":
                RuleSet(critical=(self.path,))
            case "unordered":
                RuleSet(unordered=(UnorderedRule(path=self.path, key=self.key),))
            case "compare_header":
                RuleSet(compare_headers=(self.path,))
        return self


class RuleOut(ApiModel):
    id: uuid.UUID
    kind: str
    path: str
    options: dict[str, Any]
    created_at: datetime


class SecretPut(RequestModel):
    # Printable ASCII: a secret is sent as (part of) an HTTP header value,
    # and anything else could not be sent. A trailing newline pasted along
    # with a token is the usual way this goes wrong.
    value: str = Field(min_length=1, max_length=8192, pattern=r"^[\x20-\x7e]+$")


class SecretOut(ApiModel):
    """A secret's name and age. There is no model that carries its value."""

    name: str
    updated_at: datetime


class TestCaseWrite(RequestModel):
    __test__ = False

    name: str = Field(min_length=1, max_length=200)
    endpoint_id: uuid.UUID | None = None
    steps: list[Step] = Field(min_length=1)
    noise_detection: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def _is_a_case_the_engine_accepts(self) -> Self:
        # Checks that span steps: variables captured before use, unique ids.
        Case(name=self.name, steps=tuple(self.steps), noise_detection=self.noise_detection)
        return self

    def steps_as_json(self) -> list[Any]:
        return [
            step.model_dump(mode="json", by_alias=True, exclude_defaults=True)
            for step in self.steps
        ]


class TestCaseOut(ApiModel):
    __test__ = False

    id: uuid.UUID
    name: str
    endpoint_id: uuid.UUID | None
    steps: list[Any]
    noise_detection: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
