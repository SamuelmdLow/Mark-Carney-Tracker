FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie

ENV PYTHONUNBUFFERED 1

RUN pip3 --disable-pip-version-check --no-cache-dir install -r requirements.txt \

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 