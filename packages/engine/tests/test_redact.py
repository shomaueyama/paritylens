import pytest
from paritylens_engine.redact import MASK, Redactor, is_sensitive_header


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-API-Key",
        "X-Auth-Token",
        "X-Amz-Security-Token",
        "X-Custom-Secret",
        "X-Upstream-Password",
        "Api_Key",
        "X-Client-Credential",
    ],
)
def test_sensitive_headers(name: str) -> None:
    assert is_sensitive_header(name)


@pytest.mark.parametrize("name", ["Content-Type", "Accept", "X-Request-Id", "User-Agent", "ETag"])
def test_ordinary_headers(name: str) -> None:
    assert not is_sensitive_header(name)


def test_sensitive_headers_are_masked_whatever_their_value() -> None:
    redacted = Redactor().headers({"Authorization": "Bearer abc", "Accept": "application/json"})

    assert redacted == {"Authorization": MASK, "Accept": "application/json"}


def test_known_secret_values_are_masked_wherever_they_appear() -> None:
    redactor = Redactor(["s3cr3t-token"])

    assert redactor.text("token=s3cr3t-token&x=1") == f"token={MASK}&x=1"
    assert redactor.headers({"X-Forwarded-Note": "saw s3cr3t-token"}) == {
        "X-Forwarded-Note": f"saw {MASK}"
    }


def test_a_secret_that_contains_another_is_masked_whole() -> None:
    redactor = Redactor(["abc", "abcdef"])

    assert redactor.text("abcdef") == MASK


def test_empty_secrets_are_ignored() -> None:
    """An unset environment variable must not turn every string into masks."""
    assert Redactor(["", ""]).text("hello") == "hello"


def test_a_secret_is_masked_in_its_url_encoded_and_json_escaped_forms() -> None:
    redactor = Redactor(['p@ss "word"/+é'])

    in_url = "https://api.test/x?key=p%40ss%20%22word%22%2F%2B%C3%A9"
    in_form = "key=p%40ss+%22word%22%2F%2B%C3%A9"
    in_json = '{"key": "p@ss \\"word\\"/+\\u00e9"}'
    in_json_utf8 = '{"key": "p@ss \\"word\\"/+é"}'

    for text in (in_url, in_form, in_json, in_json_utf8):
        assert "ss" not in redactor.text(text)
        assert MASK in redactor.text(text)
