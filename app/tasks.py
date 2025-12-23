"""
Celery Tasks - Background Tasks
================================

File này định nghĩa các Celery tasks để xử lý công việc nặng trong background.
This file defines Celery tasks for processing heavy work in background.

Tasks được worker pick up từ queue và xử lý bất đồng bộ.
Tasks are picked up by workers from queue and processed asynchronously.

Lợi ích / Benefits:
- Không block API requests
- Có thể retry khi thất bại
- Scale được bằng cách thêm workers
- Track được progress và kết quả
"""

# ========== IMPORTS ==========
import os
import json
import logging
import redis
from rembg import remove
from app.celery_app import celery_app


# ========== CONFIGURATION ==========
# Thư mục lưu trữ
# Storage directories
DATA_DIR = os.getenv("DATA_DIR", "/data")
RESULT_DIR = os.path.join(DATA_DIR, "results")

# Redis URL
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


# ========== INITIALIZATION ==========
# Tạo thư mục kết quả nếu chưa tồn tại
# Create result directory if not exists
os.makedirs(RESULT_DIR, exist_ok=True)

# Redis client để cập nhật job metadata
# Redis client for updating job metadata
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Logger
logger = logging.getLogger("rembg-worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))



# ========== CELERY TASKS ==========

@celery_app.task(name="app.tasks.remove_background_task", bind=True, max_retries=3)
def remove_background_task(self, upload_path: str, job_id: str):
    """
    Celery task để xóa background từ ảnh đã upload
    Celery task to remove background from uploaded image
    
    Flow xử lý / Processing flow:
    1. Cập nhật status thành PROCESSING
    2. Đọc file ảnh từ upload_path
    3. Xử lý xóa background bằng rembg
    4. Lưu kết quả vào RESULT_DIR
    5. Cập nhật status thành DONE
    6. Xóa file upload để tiết kiệm dung lượng
    
    Nếu có lỗi / If error occurs:
    - Cập nhật status thành FAILED
    - Retry tối đa 3 lần (max_retries=3)
    - Chờ 60 giây giữa các lần retry (countdown=60)
    
    Args:
        self: Task instance (vì bind=True)
        upload_path: Đường dẫn đến file đã upload
        job_id: ID của job để track progress
        
    Returns:
        dict: {"status": "DONE", "job_id": "xxx", "result_path": "..."}
        
    Raises:
        Exception: Retry task nếu xử lý thất bại
    """
    try:
        logger.info(f"Processing job {job_id} from {upload_path}")
        
        # === STEP 1: Cập nhật status sang PROCESSING ===
        # Update status to PROCESSING
        meta = {
            "status": "PROCESSING",
            "upload_path": upload_path,
            "task_id": self.request.id  # Celery task ID
        }
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        
        # === STEP 2: Đọc file input ===
        # Read input file
        with open(upload_path, "rb") as f:
            input_bytes = f.read()
        
        # === STEP 3: Xử lý xóa background ===
        # Process background removal
        # rembg.remove() là hàm chính để xóa background
        # rembg.remove() is the main function to remove background
        result_bytes = remove(input_bytes)
        
        # === STEP 4: Lưu kết quả ===
        # Save result
        result_path = os.path.join(RESULT_DIR, f"{job_id}.png")
        with open(result_path, "wb") as f:
            f.write(result_bytes)
        
        # === STEP 5: Cập nhật status sang DONE ===
        # Update status to DONE
        meta = {
            "status": "DONE",
            "upload_path": upload_path,
            "result_path": result_path,
            "task_id": self.request.id
        }
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        
        logger.info(f"Job {job_id} completed successfully")
        
        # === STEP 6: Dọn dẹp file upload ===
        # Clean up upload file
        # Xóa file upload để tiết kiệm disk space
        # Delete upload file to save disk space
        try:
            os.remove(upload_path)
        except Exception:
            # Không quan trọng nếu xóa thất bại
            # Not critical if deletion fails
            pass
        
        # Trả về kết quả
        # Return result
        return {"status": "DONE", "job_id": job_id, "result_path": result_path}
        
    except Exception as e:
        # === XỬ LÝ LỖI / ERROR HANDLING ===
        logger.exception(f"Job {job_id} failed: {e}")
        
        # Cập nhật status sang FAILED
        # Update status to FAILED
        meta = {
            "status": "FAILED",
            "error": str(e),
            "upload_path": upload_path,
            "task_id": self.request.id
        }
        redis_client.set(f"job:{job_id}", json.dumps(meta))
        
        # Retry task (tối đa 3 lần, chờ 60 giây giữa các lần)
        # Retry task (max 3 times, wait 60 seconds between retries)
        raise self.retry(exc=e, countdown=60)
