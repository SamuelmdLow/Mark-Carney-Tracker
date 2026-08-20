FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie
ENV PYTHONUNBUFFERED 1

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

COPY . .

EXPOSE 8000