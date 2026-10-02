"""Stored secrets: encrypted at rest, and impossible to read back."""

import uuid

import httpx2
import pytest
from paritylens_api.core.config import LOCAL_MASTER_KEY
from paritylens_api.core.crypto import DecryptionError, Encrypted, SecretBox, secret_context
from paritylens_api.models import Secret
from paritylens_api.testing import create_project
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.anyio

VALUE = "s3cr3t-token-value"


async def test_no_response_ever_contains_the_value(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/secrets"

    put = await alice.put(f"{path}/SHOP_TOKEN", json={"value": VALUE})
    listed = await alice.get(path)

    assert put.status_code == 200
    assert set(put.json()) == {"name", "updated_at"}
    assert [secret["name"] for secret in listed.json()] == ["SHOP_TOKEN"]
    assert VALUE not in put.text + listed.text


async def test_the_database_holds_ciphertext_not_the_value(
    alice: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    project = await create_project(alice)
    await alice.put(f"/projects/{project['id']}/secrets/SHOP_TOKEN", json={"value": VALUE})

    async with sessions() as session:
        row = (await session.scalars(select(Secret))).one()

    assert VALUE.encode() not in row.ciphertext
    box = SecretBox(LOCAL_MASTER_KEY, 1)
    context = secret_context(uuid.UUID(project["id"]), "SHOP_TOKEN")
    assert (
        box.decrypt(Encrypted(row.ciphertext, row.nonce, row.key_version), context=context) == VALUE
    )


async def test_putting_again_replaces_the_value(
    alice: httpx2.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/secrets/SHOP_TOKEN"
    await alice.put(path, json={"value": "first"})
    await alice.put(path, json={"value": "second"})

    async with sessions() as session:
        rows = (await session.scalars(select(Secret))).all()

    assert len(rows) == 1


async def test_a_secret_can_be_deleted(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)
    path = f"/projects/{project['id']}/secrets"
    await alice.put(f"{path}/SHOP_TOKEN", json={"value": VALUE})

    assert (await alice.delete(f"{path}/SHOP_TOKEN")).status_code == 204
    assert (await alice.get(path)).json() == []


@pytest.mark.parametrize("name", ["has-dash", "has space", "1starts_with_digit", "a" * 101])
async def test_secret_names_must_be_identifiers(alice: httpx2.AsyncClient, name: str) -> None:
    project = await create_project(alice)

    response = await alice.put(f"/projects/{project['id']}/secrets/{name}", json={"value": VALUE})

    assert response.status_code == 422


async def test_a_rejected_secret_value_is_not_echoed(alice: httpx2.AsyncClient) -> None:
    project = await create_project(alice)

    response = await alice.put(
        f"/projects/{project['id']}/secrets/SHOP_TOKEN", json={"value": VALUE, "extra": "x" * 3}
    )

    assert response.status_code == 422
    assert VALUE not in response.text


# --- the encryption itself --------------------------------------------------------


def box(version: int = 1) -> SecretBox:
    return SecretBox(LOCAL_MASTER_KEY, version)


def test_encrypting_twice_gives_different_ciphertexts() -> None:
    """A fresh nonce each time: equal values are not recognisable as equal."""
    first, second = box().encrypt(VALUE, context="a"), box().encrypt(VALUE, context="a")

    assert first.ciphertext != second.ciphertext
    assert box().decrypt(first, context="a") == box().decrypt(second, context="a") == VALUE


def test_a_ciphertext_moved_to_another_row_does_not_decrypt() -> None:
    encrypted = box().encrypt(VALUE, context="secret:project-1:SHOP_TOKEN")

    with pytest.raises(DecryptionError):
        box().decrypt(encrypted, context="secret:project-2:SHOP_TOKEN")


def test_a_tampered_ciphertext_does_not_decrypt() -> None:
    encrypted = box().encrypt(VALUE, context="a")
    flipped = bytes([encrypted.ciphertext[0] ^ 1]) + encrypted.ciphertext[1:]

    with pytest.raises(DecryptionError):
        box().decrypt(Encrypted(flipped, encrypted.nonce, encrypted.key_version), context="a")


def test_a_different_key_does_not_decrypt() -> None:
    other = SecretBox("AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=", 1)

    with pytest.raises(DecryptionError):
        other.decrypt(box().encrypt(VALUE, context="a"), context="a")


def test_a_value_from_another_key_version_is_refused_by_name() -> None:
    with pytest.raises(DecryptionError, match="no key for version 1"):
        box(version=2).decrypt(box(version=1).encrypt(VALUE, context="a"), context="a")


@pytest.mark.parametrize("key", ["", "c2hvcnQ=", "not base64!!"])
def test_a_master_key_of_the_wrong_size_is_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        SecretBox(key, 1)
