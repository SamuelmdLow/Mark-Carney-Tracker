FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie as builder
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM mcr.microsoft.com/devcontainers/python:3-3.14-trixie
ENV PYTHONUNBUFFERED 1

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH

RUN sudo apt-get update
RUN sudo apt-get install -y ffmpeg 

EXPOSE 8000

ENTRYPOINT ["gnuicorn", "pm_tracker:wsgi:application", "--bind", "0.0.0.0:8000"]