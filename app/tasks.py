import os
import json
import logging
import redis
from rembg import remove
from app.celery_app import celery_app

DATA_DIR = os.getenv("DATA_DIR", "/data")
RESULT_DIR = os.path.join(DATA_DIR, "results")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

os.makedirs(RESULT_DIR, exist_ok=True)

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
logger = logging.getLogger("rembg-worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

@celery_app.task(name="app.tasks.remove_background_task", bind=True, max_retries=3)
def remove_background_task(self, upload_path: str, job_id: str):
    """
    Celery task to remove background from an uploaded image.
    """
    try:
        logger.info(f"Processing job {job_id} from {upload_path}")
        
        # Update status to PROCESSING
        meta = {"status": "PROCESSING", "upload_path": upload_path, "task_id": self.request.id}
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        
        # Read input image
        with open(upload_path, "rb") as f:
            input_bytes = f.read()
        
        # Remove background
        result_bytes = remove(input_bytes)
        
        # Save result
        result_path = os.path.join(RESULT_DIR, f"{job_id}.png")
        with open(result_path, "wb") as f:
            f.write(result_bytes)
        
        # Update status to DONE
        meta = {"status": "DONE", "upload_path": upload_path, "result_path": result_path, "task_id": self.request.id}
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        
        logger.info(f"Job {job_id} completed successfully")
        
        # Optionally clean up upload file
        try:
            os.remove(upload_path)
        except Exception:
            pass
        
        return {"status": "DONE", "job_id": job_id, "result_path": result_path}
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        meta = {"status": "FAILED", "error": str(e), "upload_path": upload_path, "task_id": self.request.id}
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        raise self.retry(exc=e, countdown=60)
