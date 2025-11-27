from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import asyncio
import uuid
import logging
from rembg import remove
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import redis
import json

# Config via env
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DATA_DIR = os.getenv("DATA_DIR", "/data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
RESULT_DIR = os.path.join(DATA_DIR, "results")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MODEL_PREWARM = os.getenv("MODEL_PREWARM", "1") == "1"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# Redis client for job metadata (used in async flow)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title="rembg-fastapi", version="0.2")

# CORS (tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("rembg-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Prometheus metrics
REQ_COUNT = Counter("rembg_requests_total", "Total requests", ["endpoint", "method", "status"])
INFER_HIST = Histogram("rembg_inference_seconds", "Inference processing time seconds")

@app.on_event("startup")
async def startup_event():
    logger.info("Starting rembg-fastapi...")
    if MODEL_PREWARM:
        # Pre-warm model to avoid first-request latency
        try:
            logger.info("Pre-warming model (running a tiny inference)...")
            import io
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
            dummy = buf.getvalue()
            await asyncio.to_thread(remove, dummy)
            logger.info("Model pre-warm completed.")
        except Exception as e:
            logger.exception("Model pre-warm failed: %s", e)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.post("/remove")
async def remove_background(file: UploadFile = File(...)):
    endpoint = "/remove"
    try:
        if not file.content_type.startswith("image/"):
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Uploaded file must be an image")

        contents = await file.read()
        if len(contents) == 0:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Empty file")
        if len(contents) > MAX_UPLOAD_BYTES:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="413").inc()
            raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB} MB allowed")

        # Run remove in a thread to avoid blocking event loop
        with INFER_HIST.time():
            result_bytes = await asyncio.to_thread(remove, contents)

        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="200").inc()
        headers = {"Content-Disposition": 'inline; filename="result.png"'}
        return Response(content=result_bytes, media_type="image/png", headers=headers)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Processing error")
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

@app.post("/remove-async")
async def remove_async(file: UploadFile = File(...)):
    endpoint = "/remove-async"
    try:
        if not file.content_type.startswith("image/"):
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Uploaded file must be an image")

        contents = await file.read()
        if len(contents) == 0:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Empty file")
        if len(contents) > MAX_UPLOAD_BYTES:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="413").inc()
            raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB} MB allowed")

        job_id = uuid.uuid4().hex
        suffix = os.path.splitext(file.filename or "")[1] or ".bin"
        upload_path = os.path.join(UPLOAD_DIR, f"{job_id}{suffix}")
        with open(upload_path, "wb") as f:
            f.write(contents)

        from app.celery_app import celery_app
        meta = {"status": "PENDING", "upload_path": upload_path}
        redis_client.set(f"job:{job_id}", json.dumps(meta))

        res = celery_app.send_task("app.tasks.remove_background_task", args=[upload_path, job_id], kwargs={}, queue="rembg")
        meta.update({"task_id": res.id})
        redis_client.set(f"job:{job_id}", json.dumps(meta))

        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="202").inc()
        return JSONResponse(status_code=202, content={"job_id": job_id})
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Enqueue error")
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Enqueue error: {str(e)}")

@app.get("/status/{job_id}")
async def status(job_id: str):
    endpoint = "/status"
    try:
        meta_raw = redis_client.get(f"job:{job_id}")
        if not meta_raw:
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="404").inc()
            raise HTTPException(status_code=404, detail="Job not found")
        meta = json.loads(meta_raw)
        status = meta.get("status", "UNKNOWN")
        result = {"job_id": job_id, "status": status}
        if status == "DONE":
            result["download_url"] = f"/download/{job_id}"
        elif status == "FAILED":
            result["error"] = meta.get("error")
        REQ_COUNT.labels(endpoint=endpoint, method="GET", status="200").inc()
        return result
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Status error")
        REQ_COUNT.labels(endpoint=endpoint, method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Status error: {str(e)}")

@app.get("/download/{job_id}")
async def download(job_id: str):
    endpoint = "/download"
    try:
        result_path = os.path.join(RESULT_DIR, f"{job_id}.png")
        if os.path.exists(result_path):
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="200").inc()
            return FileResponse(result_path, media_type="image/png", filename=f"{job_id}.png")
        else:
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="404").inc()
            raise HTTPException(status_code=404, detail="Result not ready")
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Download error")
        REQ_COUNT.labels(endpoint=endpoint, method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")
