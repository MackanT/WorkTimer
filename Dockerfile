FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# set desired timezone
ENV TZ=Europe/Stockholm

# install tzdata and configure timezone non-interactively
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

ADD . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

EXPOSE 8080

ENTRYPOINT ["uv", "run", "-m", "src.main"]