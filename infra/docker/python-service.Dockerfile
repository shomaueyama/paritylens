# One image definition for every Python service in the workspace.
# The build context is the repository root.
#
#   --build-arg PACKAGE=paritylens-api   workspace package to install
#   --build-arg APP=paritylens_api.main:app   ASGI app for uvicorn to serve

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /workspace

COPY pyproject.toml uv.lock .python-version ./
COPY apps/api apps/api
COPY packages packages
COPY demo demo

ARG PACKAGE
# --no-editable installs the package itself into the virtualenv, so the
# final image needs the virtualenv only and not the source tree.
RUN uv sync --frozen --no-dev --no-editable --package ${PACKAGE}


FROM python:3.13-slim
RUN useradd --system --uid 10001 app
COPY --from=build /workspace/.venv /workspace/.venv
ENV PATH="/workspace/.venv/bin:$PATH"
USER app

ARG APP
ENV APP=${APP}
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn ${APP} --host 0.0.0.0 --port 8000"]
