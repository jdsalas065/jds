# rembg-service

A FastAPI + Celery service for removing backgrounds from images using [rembg](https://github.com/danielgatis/rembg).

## Features

- **Synchronous API** (`/remove`) - Upload an image and get the result immediately
- **Asynchronous API** (`/remove-async`) - Submit a job and poll for results
- **Celery Workers** - Background processing for async jobs
- **Redis** - Job queue and metadata storage
- **Prometheus Metrics** - Built-in metrics endpoint
- **Docker Compose** - Easy deployment

## Quick Start

### Using Docker Compose

```bash
# Start all services
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Start Redis (required)
docker run -d -p 6379:6379 redis:7-alpine

# Start API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start Celery worker (in another terminal)
celery -A app.celery_app worker --loglevel=info -Q rembg
```

## API Endpoints

### Health Check
```bash
GET /health
# Response: {"status": "ok"}
```

### Prometheus Metrics
```bash
GET /metrics
```

### Remove Background (Sync)
```bash
POST /remove
# Content-Type: multipart/form-data
# Body: file=@image.jpg

curl -X POST -F "file=@image.jpg" http://localhost:8000/remove -o result.png
```

### Remove Background (Async)
```bash
# Submit job
POST /remove-async
# Response: {"job_id": "abc123"}

# Check status
GET /status/{job_id}
# Response: {"job_id": "abc123", "status": "DONE", "download_url": "/download/abc123"}

# Download result
GET /download/{job_id}
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `DATA_DIR` | `/data` | Directory for uploads and results |
| `MAX_UPLOAD_MB` | `15` | Maximum upload size in MB |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MODEL_PREWARM` | `1` | Pre-warm model on startup (1=yes, 0=no) |
| `CORS_ALLOW_ORIGINS` | `*` | CORS allowed origins (comma-separated) |

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── celery_app.py    # Celery configuration
│   └── tasks.py         # Celery tasks
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## License

MIT
