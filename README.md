# rembg-service

A FastAPI + Celery service for removing backgrounds from images using [rembg](https://github.com/danielgatis/rembg).

## Features

- **Synchronous API** (`/remove`) - Upload an image and get the result immediately
- **Asynchronous API** (`/remove-async`) - Submit a job and poll for results
- **Celery Workers** - Background processing for async jobs
- **Redis** - Job queue and metadata storage
- **Prometheus Metrics** - Built-in metrics endpoint
- **Docker Compose** - Easy deployment

## Prerequisites

Before deploying locally, make sure you have the following installed:

### For Docker Deployment:
- [Docker](https://docs.docker.com/get-docker/) (version 20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (version 2.0+)

### For Manual/Development Deployment:
- [Python](https://www.python.org/downloads/) 3.9+ (recommended: 3.11)
- [Redis](https://redis.io/download/) server OR Docker (to run Redis container)
- Git (to clone the repository)

## Detailed Local Deployment Guide

### Option 1: Deploy with Docker Compose (Recommended)

This is the easiest and recommended method for local deployment.

#### Step 1: Clone the repository
```bash
git clone https://github.com/jdsalas065/jds.git
cd jds
```

#### Step 2: Configure environment (optional)
```bash
# Copy example environment file
cp .env.example .env

# Edit .env file if needed (default values work for local deployment)
# nano .env
```

#### Step 3: Build and start all services
```bash
# Build images and start containers in detached mode
docker-compose up -d --build

# View logs (optional)
docker-compose logs -f
```

#### Step 4: Verify deployment
```bash
# Check if all containers are running
docker-compose ps

# Test health endpoint
curl http://localhost:8000/health
# Expected response: {"status":"ok"}

# Test metrics endpoint
curl http://localhost:8000/metrics
```

#### Step 5: Test the API
```bash
# Test synchronous background removal (replace test.jpg with your image)
curl -X POST -F "file=@test.jpg" http://localhost:8000/remove -o result.png

# Test asynchronous background removal
curl -X POST -F "file=@test.jpg" http://localhost:8000/remove-async
# Response: {"job_id":"abc123..."}

# Check job status
curl http://localhost:8000/status/{job_id}

# Download result when status is "DONE"
curl http://localhost:8000/download/{job_id} -o result.png
```

#### Stop and cleanup
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (deletes all data)
docker-compose down -v
```

---

### Option 2: Manual Development Setup

Use this method for development or when Docker is not available.

#### Step 1: Clone the repository
```bash
git clone https://github.com/jdsalas065/jds.git
cd jds
```

#### Step 2: Create Python virtual environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate

# On Windows (Command Prompt):
venv\Scripts\activate.bat

# On Windows (PowerShell):
venv\Scripts\Activate.ps1
```

#### Step 3: Install Python dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 4: Start Redis server

**Option A: Using Docker (recommended)**
```bash
docker run -d --name redis-local -p 6379:6379 redis:7-alpine
```

**Option B: Using local Redis installation**
```bash
# On Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis-server

# On macOS with Homebrew
brew install redis
brew services start redis

# On Windows
# Download from https://github.com/microsoftarchive/redis/releases
# Run redis-server.exe
```

#### Step 5: Create data directories
```bash
mkdir -p /tmp/rembg-data/uploads /tmp/rembg-data/results
```

#### Step 6: Set environment variables
```bash
# On Linux/Mac:
export REDIS_URL="redis://localhost:6379/0"
export DATA_DIR="/tmp/rembg-data"
export MAX_UPLOAD_MB="15"
export LOG_LEVEL="INFO"
export MODEL_PREWARM="1"

# On Windows (Command Prompt):
set REDIS_URL=redis://localhost:6379/0
set DATA_DIR=C:\tmp\rembg-data
set MAX_UPLOAD_MB=15
set LOG_LEVEL=INFO
set MODEL_PREWARM=1

# On Windows (PowerShell):
$env:REDIS_URL="redis://localhost:6379/0"
$env:DATA_DIR="C:\tmp\rembg-data"
$env:MAX_UPLOAD_MB="15"
$env:LOG_LEVEL="INFO"
$env:MODEL_PREWARM="1"
```

#### Step 7: Start the FastAPI server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Step 8: Start Celery worker (in a new terminal)
```bash
# Activate virtual environment first
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Set environment variables (same as Step 6)

# Start worker
celery -A app.celery_app worker --loglevel=info -Q rembg
```

#### Step 9: Verify deployment
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test with an image
curl -X POST -F "file=@your-image.jpg" http://localhost:8000/remove -o result.png
```

---

## Troubleshooting

### Common Issues

#### 1. Docker: "Cannot connect to the Docker daemon"
```bash
# Make sure Docker is running
sudo systemctl start docker  # Linux
# Or start Docker Desktop on Windows/Mac
```

#### 2. Redis connection error
```bash
# Check if Redis is running
redis-cli ping
# Should return: PONG

# If not running, start it:
docker start redis-local  # If using Docker
# Or: sudo systemctl start redis-server  # If installed locally
```

#### 3. "No module named 'rembg'" or other import errors
```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

#### 4. Port 8000 already in use
```bash
# Find process using port 8000
lsof -i :8000  # Linux/Mac
netstat -ano | findstr :8000  # Windows

# Kill the process or use a different port
uvicorn app.main:app --port 8001
```

#### 5. First request is slow
This is normal! The rembg model is loaded on the first request. To pre-warm:
- Set `MODEL_PREWARM=1` environment variable
- The model will be loaded during startup

---

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
