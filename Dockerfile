# Python base image
FROM python:3.10-slim

# Workdir
WORKDIR /app

# System deps (ffmpeg for YouTube audio conversion)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Entrypoint
CMD ["python", "main.py"]
