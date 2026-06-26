FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie

ENV PYTHONUNBUFFERED 1

RUN pip3 install -r requirements.txt
RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 