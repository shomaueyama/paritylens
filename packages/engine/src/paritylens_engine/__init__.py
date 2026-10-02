"""ParityLens comparison engine.

Pure Python, no web framework and no database. Everything that decides
whether two API responses are compatible lives here, so it can be tested
without infrastructure and shared by the CLI and the hosted worker.
"""

__version__ = "0.1.0"
