'''
FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie as builder
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt
'''

FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie
ENV PYTHONUNBUFFERED 1

WORKDIR /app

#COPY --from=builder /venv /venv
#ENV PATH="/venv/bin:$PATH"

COPY . .

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

EXPOSE 8000