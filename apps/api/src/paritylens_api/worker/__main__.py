"""Entry point: python -m paritylens_api.worker"""

import asyncio

from paritylens_api.core.config import get_settings
from paritylens_api.core.logging import configure_logging
from paritylens_api.db import get_session_factory
from paritylens_api.worker.loop import run_forever

if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_forever(get_session_factory(), get_settings()))
