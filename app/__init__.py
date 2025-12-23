"""
App Package - Package ứng dụng
===============================

Package này chứa toàn bộ source code của FastAPI application.
This package contains all source code of the FastAPI application.

Cấu trúc / Structure:
--------------------
app/
├── __init__.py       - Package initialization (file này / this file)
├── main.py           - FastAPI application với các endpoints
│                       FastAPI application with endpoints
├── celery_app.py     - Celery configuration và initialization
│                       Celery configuration and initialization
└── tasks.py          - Celery tasks cho background processing
                        Celery tasks for background processing

Kiến trúc tổng quan / Overall Architecture:
-------------------------------------------

1. FastAPI (main.py):
   - Xử lý HTTP requests
   - Handles HTTP requests
   - Sync API (/remove): Xử lý ngay và trả về kết quả
   - Sync API (/remove): Process immediately and return result
   - Async API (/remove-async): Enqueue job và trả về job_id
   - Async API (/remove-async): Enqueue job and return job_id

2. Celery (celery_app.py + tasks.py):
   - Worker xử lý background jobs
   - Worker processes background jobs
   - Chạy độc lập với FastAPI
   - Runs independently from FastAPI
   - Có thể scale bằng cách chạy nhiều workers
   - Can scale by running multiple workers

3. Redis:
   - Message broker: Queue để gửi tasks
   - Message broker: Queue for sending tasks
   - Result backend: Lưu kết quả tasks
   - Result backend: Store task results
   - Job metadata: Lưu trạng thái jobs
   - Job metadata: Store job status

Cách chạy / How to run:
-----------------------
1. Start Redis:
   docker run -d -p 6379:6379 redis:7-alpine

2. Start FastAPI:
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

3. Start Celery Worker:
   celery -A app.celery_app worker --loglevel=info -Q rembg

Hoặc dùng Docker Compose / Or use Docker Compose:
   docker-compose up -d
"""

