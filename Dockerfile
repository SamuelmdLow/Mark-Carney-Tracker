FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie
ENV PYTHONUNBUFFERED 1

WORKDIR /app

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

COPY . .

EXPOSE 8000