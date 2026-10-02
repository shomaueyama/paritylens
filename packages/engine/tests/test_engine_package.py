import paritylens_engine


def test_version_is_exposed() -> None:
    """The version ends up in every RunReport, so it has to be importable."""
    assert paritylens_engine.__version__ == "0.1.0"
