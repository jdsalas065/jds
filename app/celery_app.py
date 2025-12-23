"""
Celery Application Configuration - Cấu hình Celery
===================================================

File này cấu hình Celery app để xử lý background tasks bất đồng bộ.
This file configures Celery app for processing asynchronous background tasks.

Celery là gì? / What is Celery?
- Là distributed task queue để chạy tasks bất đồng bộ
- Is a distributed task queue for running asynchronous tasks
- Giúp xử lý công việc nặng mà không block API
- Helps process heavy work without blocking the API
- Có thể scale bằng cách thêm workers
- Can scale by adding more workers

Các thành phần / Components:
1. Celery app instance - Instance Celery chính
2. Broker (Redis) - Queue để gửi/nhận tasks
3. Backend (Redis) - Nơi lưu kết quả tasks
4. Configuration - Cấu hình serialize, timezone, routing
"""

# ========== IMPORTS ==========
from celery import Celery
import os


# ========== CONFIGURATION ==========
# Redis URL dùng cho cả broker và backend
# Redis URL for both broker and backend
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


# ========== CELERY APP INSTANCE ==========
celery_app = Celery(
    "rembg-worker",  # Tên của worker
    broker=REDIS_URL,  # Broker URL - nơi queue tasks
    backend=REDIS_URL,  # Backend URL - nơi lưu kết quả
)


# ========== CELERY CONFIGURATION ==========
celery_app.conf.update(
    # Serialization - Định dạng serialize data
    task_serializer="json",  # Serialize tasks thành JSON (an toàn, dễ debug)
    accept_content=["json"],  # Chỉ chấp nhận content type JSON
    result_serializer="json",  # Serialize kết quả thành JSON
    
    # Timezone - Múi giờ
    timezone="UTC",  # Dùng UTC để tránh vấn đề timezone
    enable_utc=True,  # Bật UTC
    
    # Task Routing - Định tuyến tasks đến queues
    # Cấu hình task nào đi vào queue nào
    # Configure which task goes to which queue
    task_routes={
        "app.tasks.remove_background_task": {"queue": "rembg"},  # Task xóa background vào queue "rembg"
    },
)
