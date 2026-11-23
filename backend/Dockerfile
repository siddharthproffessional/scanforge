FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml .
COPY scanforge ./scanforge
RUN pip install --no-cache-dir .
ENV SCANFORGE_DATA=/data
EXPOSE 8000
CMD ["uvicorn", "scanforge.api:app", "--host", "0.0.0.0", "--port", "8000"]
