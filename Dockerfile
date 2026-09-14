FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# set desired timezone
ENV TZ=Europe/Stockholm

# Inside the container the app must bind all interfaces for the port mapping
# to work — reachability from outside the HOST is governed by the compose
# port mapping, not this. (The bare-metal default is 127.0.0.1.)
ENV HOST=0.0.0.0
# Lets the app detect it runs in Docker (update instructions differ).
ENV WORKTIMER_DOCKER=1

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

ENTRYPOINT ["uv", "run", "-m", "main"]