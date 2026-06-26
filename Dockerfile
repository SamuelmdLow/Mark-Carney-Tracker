FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie

ENV PYTHONUNBUFFERED 1

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

WORKDIR /app

COPY . .

EXPOSE 8000

ENTRYPOINT ["pip", "install", "-r", "requirements.txt"]