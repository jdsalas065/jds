"""
FastAPI Main Application - Ứng dụng chính FastAPI
=================================================

File này chứa cấu hình và định nghĩa các endpoint cho API service.
This file contains configuration and endpoint definitions for the API service.

Các thành phần chính / Main components:
1. Configuration - Cấu hình từ biến môi trường
2. FastAPI app initialization - Khởi tạo ứng dụng FastAPI
3. CORS middleware - Middleware xử lý CORS
4. API endpoints - Các điểm cuối API
5. Prometheus metrics - Metrics để monitor
"""

# ========== IMPORTS - Thư viện cần thiết ==========
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import asyncio
import uuid
import logging
import io
from PIL import Image
from rembg import remove
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import redis
import json
from app.celery_app import celery_app


# ========== CONFIGURATION - Cấu hình từ biến môi trường ==========
# Đọc cấu hình từ environment variables hoặc sử dụng giá trị mặc định
# Read configuration from environment variables or use default values

# Kích thước tối đa file upload (MB)
# Maximum upload file size (MB)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Thư mục lưu trữ dữ liệu
# Data storage directory
DATA_DIR = os.getenv("DATA_DIR", "/data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")  # Thư mục lưu file upload
RESULT_DIR = os.path.join(DATA_DIR, "results")  # Thư mục lưu kết quả

# Redis connection URL cho job queue và metadata
# Redis connection URL for job queue and metadata
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Pre-warm model khi khởi động để giảm độ trễ request đầu tiên
# Pre-warm model on startup to reduce first request latency
MODEL_PREWARM = os.getenv("MODEL_PREWARM", "1") == "1"


# ========== INITIALIZATION - Khởi tạo ==========

# Tạo thư mục nếu chưa tồn tại
# Create directories if they don't exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# Redis client để lưu metadata của các job async
# Redis client for storing async job metadata
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Logger để ghi log
# Logger for logging
logger = logging.getLogger("rembg-service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# ========== PROMETHEUS METRICS - Metrics để monitor ==========
# Counter đếm số lượng requests
# Counter for tracking request count
REQ_COUNT = Counter("rembg_requests_total", "Total requests", ["endpoint", "method", "status"])

# Histogram đo thời gian xử lý inference
# Histogram for measuring inference processing time
INFER_HIST = Histogram("rembg_inference_seconds", "Inference processing time seconds")


# ========== LIFESPAN EVENTS - Sự kiện vòng đời ứng dụng ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Quản lý vòng đời ứng dụng (startup và shutdown)
    Manage application lifespan (startup and shutdown)
    
    - Startup: Pre-warm model nếu được bật để giảm độ trễ request đầu tiên
    - Startup: Pre-warm model if enabled to reduce first request latency
    - Shutdown: Dọn dẹp resources
    - Shutdown: Clean up resources
    """
    # === STARTUP - Khởi động ===
    logger.info("Starting rembg-fastapi...")
    
    if MODEL_PREWARM:
        # Pre-warm model bằng cách chạy một inference nhỏ
        # Pre-warm model by running a tiny inference
        try:
            logger.info("Pre-warming model (running a tiny inference)...")
            # Tạo một ảnh 1x1 pixel để test
            # Create a 1x1 pixel image to test
            buf = io.BytesIO()
            Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
            dummy = buf.getvalue()
            # Chạy remove trong thread pool để không block event loop
            # Run remove in thread pool to not block event loop
            await asyncio.to_thread(remove, dummy)
            logger.info("Model pre-warm completed.")
        except Exception as e:
            logger.exception("Model pre-warm failed: %s", e)
    
    yield  # App đang chạy / App is running
    
    # === SHUTDOWN - Tắt ===
    logger.info("Shutting down rembg-fastapi...")


# ========== FASTAPI APP INITIALIZATION - Khởi tạo ứng dụng FastAPI ==========
app = FastAPI(
    title="rembg-fastapi",  # Tên API
    version="0.2",  # Phiên bản
    lifespan=lifespan  # Gắn lifespan manager
)


# ========== CORS MIDDLEWARE - Cấu hình CORS ==========
# CORS (Cross-Origin Resource Sharing) cho phép frontend từ domain khác gọi API
# CORS allows frontend from different domains to call the API
# Chú ý: Trong production nên giới hạn allow_origins thay vì "*"
# Note: In production, limit allow_origins instead of "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),  # Các domain được phép
    allow_credentials=True,  # Cho phép gửi credentials (cookies, auth headers)
    allow_methods=["*"],  # Cho phép tất cả HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Cho phép tất cả headers
)


# ========== API ENDPOINTS - Các điểm cuối API ==========

# ---------- HEALTH CHECK ENDPOINT - Kiểm tra sức khỏe API ----------
@app.get("/health")
async def health():
    """
    Endpoint để kiểm tra xem API có đang hoạt động không
    Endpoint to check if the API is running
    
    Returns:
        {"status": "ok"} - API đang hoạt động bình thường
    """
    return {"status": "ok"}


# ---------- METRICS ENDPOINT - Prometheus metrics ----------
@app.get("/metrics")
async def metrics():
    """
    Endpoint để export Prometheus metrics
    Endpoint to export Prometheus metrics
    
    Metrics bao gồm / Metrics include:
    - rembg_requests_total: Tổng số requests theo endpoint, method, status
    - rembg_inference_seconds: Thời gian xử lý inference
    
    Returns:
        Prometheus metrics format
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------- SYNCHRONOUS BACKGROUND REMOVAL - Xóa background đồng bộ ----------
@app.post("/remove")
async def remove_background(file: UploadFile = File(...)):
    """
    Xóa background khỏi ảnh (đồng bộ - trả về kết quả ngay lập tức)
    Remove background from image (synchronous - returns result immediately)
    
    Flow / Luồng xử lý:
    1. Validate file (kiểm tra file hợp lệ)
    2. Đọc nội dung file
    3. Xử lý xóa background
    4. Trả về ảnh kết quả
    
    Args:
        file: File ảnh upload (PNG, JPG, etc.)
        
    Returns:
        Image với background đã bị xóa (format PNG)
        
    Raises:
        400: File không phải ảnh hoặc file rỗng
        413: File quá lớn (> MAX_UPLOAD_MB)
        500: Lỗi xử lý
    """
    endpoint = "/remove"
    try:
        # === VALIDATION - Kiểm tra file ===
        # Kiểm tra content type phải là image
        # Check content type must be image
        if not file.content_type.startswith("image/"):
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Uploaded file must be an image")

        # Đọc nội dung file
        # Read file contents
        contents = await file.read()
        
        # Kiểm tra file không rỗng
        # Check file is not empty
        if len(contents) == 0:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="400").inc()
            raise HTTPException(status_code=400, detail="Empty file")
        
        # Kiểm tra kích thước file
        # Check file size
        if len(contents) > MAX_UPLOAD_BYTES:
            REQ_COUNT.labels(endpoint=endpoint, method="POST", status="413").inc()
            raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_MB} MB allowed")

        # === PROCESSING - Xử lý ===
        # Chạy remove trong thread pool để không block asyncio event loop
        # Run remove in thread pool to avoid blocking asyncio event loop
        # Đồng thời đo thời gian xử lý cho metrics
        # Also measure processing time for metrics
        with INFER_HIST.time():
            result_bytes = await asyncio.to_thread(remove, contents)

        # === RESPONSE - Trả về kết quả ===
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="200").inc()
        headers = {"Content-Disposition": 'inline; filename="result.png"'}
        return Response(content=result_bytes, media_type="image/png", headers=headers)
        
    except HTTPException as he:
        # Re-raise HTTPException để FastAPI xử lý
        # Re-raise HTTPException for FastAPI to handle
        raise he
    except Exception as e:
        # Log và trả về lỗi 500 cho các exception khác
        # Log and return 500 error for other exceptions
        logger.exception("Processing error")
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


# ---------- ASYNCHRONOUS BACKGROUND REMOVAL - Xóa background bất đồng bộ ----------
@app.post("/remove-async")
async def remove_async(file: UploadFile = File(...)):
    """
    Xóa background bất đồng bộ qua Celery worker
    Remove background asynchronously via Celery worker
    
    Flow / Luồng xử lý:
    1. Validate file
    2. Lưu file vào UPLOAD_DIR
    3. Tạo job_id và lưu metadata vào Redis
    4. Gửi task đến Celery worker
    5. Trả về job_id để client theo dõi
    
    Phù hợp cho / Suitable for:
    - File lớn cần xử lý lâu
    - Xử lý batch nhiều file
    - Không muốn timeout khi xử lý
    
    Args:
        file: File ảnh upload
        
    Returns:
        {"job_id": "xxx"} - ID để check status và download kết quả
        
    Raises:
        400: File không hợp lệ
        413: File quá lớn
        500: Lỗi enqueue job
    """
    endpoint = "/remove-async"
    try:
        # === VALIDATION - Kiểm tra file ===
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

        # === SAVE FILE - Lưu file ===
        # Tạo job_id unique
        # Generate unique job_id
        job_id = uuid.uuid4().hex
        
        # Lấy extension từ filename (ví dụ: .jpg, .png)
        # Get extension from filename (e.g., .jpg, .png)
        suffix = os.path.splitext(file.filename or "")[1] or ".bin"
        upload_path = os.path.join(UPLOAD_DIR, f"{job_id}{suffix}")
        
        # Lưu file vào disk
        # Save file to disk
        with open(upload_path, "wb") as f:
            f.write(contents)

        # === CREATE JOB - Tạo job metadata ===
        # Lưu metadata ban đầu vào Redis
        # Save initial metadata to Redis
        meta = {"status": "PENDING", "upload_path": upload_path}
        redis_client.set(f"job:{job_id}", json.dumps(meta))

        # === ENQUEUE TASK - Gửi task đến Celery ===
        # Gửi task đến queue "rembg" để worker xử lý
        # Send task to "rembg" queue for worker to process
        res = celery_app.send_task(
            "app.tasks.remove_background_task",  # Task name
            args=[upload_path, job_id],  # Arguments
            kwargs={},
            queue="rembg"  # Queue name
        )
        
        # Cập nhật metadata với task_id
        # Update metadata with task_id
        meta.update({"task_id": res.id})
        redis_client.set(f"job:{job_id}", json.dumps(meta))

        # === RESPONSE - Trả về job_id ===
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="202").inc()
        return JSONResponse(status_code=202, content={"job_id": job_id})
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Enqueue error")
        REQ_COUNT.labels(endpoint=endpoint, method="POST", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Enqueue error: {str(e)}")


# ---------- JOB STATUS ENDPOINT - Kiểm tra trạng thái job ----------
@app.get("/status/{job_id}")
async def status(job_id: str):
    """
    Kiểm tra trạng thái của async job
    Check status of async job
    
    Các trạng thái / Possible statuses:
    - PENDING: Job đang chờ xử lý
    - PROCESSING: Job đang được xử lý
    - DONE: Job hoàn thành, có thể download kết quả
    - FAILED: Job thất bại
    
    Args:
        job_id: ID của job (nhận từ /remove-async)
        
    Returns:
        {
            "job_id": "xxx",
            "status": "DONE|PENDING|PROCESSING|FAILED",
            "download_url": "/download/xxx" (nếu DONE),
            "error": "..." (nếu FAILED)
        }
        
    Raises:
        404: Job không tồn tại
        500: Lỗi đọc metadata
    """
    endpoint = "/status"
    try:
        # Lấy metadata từ Redis
        # Get metadata from Redis
        meta_raw = redis_client.get(f"job:{job_id}")
        
        if not meta_raw:
            # Job không tồn tại
            # Job not found
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="404").inc()
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Parse JSON metadata
        meta = json.loads(meta_raw)
        status = meta.get("status", "UNKNOWN")
        
        # Tạo response object
        # Create response object
        result = {"job_id": job_id, "status": status}
        
        # Thêm download_url nếu job đã hoàn thành
        # Add download_url if job is done
        if status == "DONE":
            result["download_url"] = f"/download/{job_id}"
        # Thêm error message nếu job thất bại
        # Add error message if job failed
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


# ---------- DOWNLOAD RESULT ENDPOINT - Tải kết quả ----------
@app.get("/download/{job_id}")
async def download(job_id: str):
    """
    Tải kết quả của async job
    Download result of async job
    
    Chỉ có thể download khi job status = DONE
    Can only download when job status = DONE
    
    Args:
        job_id: ID của job
        
    Returns:
        File ảnh PNG với background đã xóa
        
    Raises:
        404: Kết quả chưa sẵn sàng hoặc không tồn tại
        500: Lỗi đọc file
    """
    endpoint = "/download"
    try:
        # Đường dẫn đến file kết quả
        # Path to result file
        result_path = os.path.join(RESULT_DIR, f"{job_id}.png")
        
        # Kiểm tra file có tồn tại không
        # Check if file exists
        if os.path.exists(result_path):
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="200").inc()
            # Trả về file với FileResponse
            # Return file with FileResponse
            return FileResponse(
                result_path,
                media_type="image/png",
                filename=f"{job_id}.png"
            )
        else:
            # File chưa sẵn sàng (job chưa hoàn thành)
            # File not ready (job not completed)
            REQ_COUNT.labels(endpoint=endpoint, method="GET", status="404").inc()
            raise HTTPException(status_code=404, detail="Result not ready")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Download error")
        REQ_COUNT.labels(endpoint=endpoint, method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")
