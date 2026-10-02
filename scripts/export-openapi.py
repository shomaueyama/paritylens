"""Write the API's OpenAPI document to stdout.

The web app's TypeScript types are generated from this, so the two sides
cannot drift apart silently:

    uv run python scripts/export-openapi.py > apps/web/src/lib/api/openapi.json
    (cd apps/web && npm run generate:api)
"""

import json
import sys

from paritylens_api.main import create_app

json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
