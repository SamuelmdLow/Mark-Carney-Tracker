FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie
ENV PYTHONUNBUFFERED 1

WORKDIR /app

#COPY --from=builder /venv /venv
#ENV PATH="/venv/bin:$PATH"

COPY . .

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

EXPOSE 8000