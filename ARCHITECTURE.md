# Kiến Trúc FastAPI Application / FastAPI Application Architecture

## Tổng quan / Overview

Đây là một ứng dụng FastAPI hoàn chỉnh với các thành phần cơ bản để xây dựng một web service production-ready.

This is a complete FastAPI application with essential components for building a production-ready web service.

## Sơ đồ kiến trúc / Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLIENT / NGƯỜI DÙNG                     │
│                    (Web Browser, Mobile App, etc.)               │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTP Requests
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FASTAPI SERVER                           │
│                         (app/main.py)                            │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  API Endpoints / Điểm cuối API                           │  │
│  │  • GET  /health        - Health check                    │  │
│  │  • GET  /metrics       - Prometheus metrics              │  │
│  │  • POST /remove        - Sync background removal         │  │
│  │  • POST /remove-async  - Async background removal        │  │
│  │  • GET  /status/{id}   - Check job status                │  │
│  │  • GET  /download/{id} - Download result                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Middleware / Tầng xử lý trung gian                      │  │
│  │  • CORS - Cross-Origin Resource Sharing                  │  │
│  │  • Logging - Ghi log                                     │  │
│  │  • Metrics - Thu thập metrics                            │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────┬──────────────────────────────────┬──────────────────┘
           │                                   │
           │ Sync Processing                   │ Async Task Queue
           │ (Direct response)                 │ (Send to queue)
           │                                   │
           ▼                                   ▼
    ┌─────────────┐                   ┌──────────────────┐
    │   rembg     │                   │   REDIS SERVER   │
    │  Library    │                   │  (Message Broker)│
    │             │                   │                  │
    │ Background  │                   │  • Job Queue     │
    │  Removal    │                   │  • Job Metadata  │
    │  Processing │                   │  • Task Results  │
    └─────────────┘                   └────────┬─────────┘
                                               │
                                               │ Pull tasks
                                               ▼
                                   ┌────────────────────────┐
                                   │   CELERY WORKERS       │
                                   │   (app/celery_app.py + │
                                   │    app/tasks.py)       │
                                   │                        │
                                   │  Background Processing │
                                   │  • Read from queue     │
                                   │  • Process image       │
                                   │  • Update status       │
                                   │  • Save results        │
                                   │  • Retry on failure    │
                                   └────────────────────────┘
```

## Các thành phần chính / Main Components

### 1. FastAPI Server (app/main.py)

**Vai trò / Role**: Web server xử lý HTTP requests từ client

**Chức năng / Functions**:
- Nhận requests từ client
- Validate dữ liệu đầu vào
- Xử lý đồng bộ (sync) - trả về ngay kết quả
- Enqueue jobs bất đồng bộ (async) vào Redis
- Quản lý CORS, logging, metrics

**Các endpoint chính / Main endpoints**:

| Endpoint | Method | Mô tả / Description |
|----------|--------|---------------------|
| `/health` | GET | Kiểm tra server có sống không / Check if server is alive |
| `/metrics` | GET | Prometheus metrics để monitor / Prometheus metrics for monitoring |
| `/remove` | POST | Xóa background đồng bộ / Synchronous background removal |
| `/remove-async` | POST | Gửi job xóa background bất đồng bộ / Enqueue async background removal job |
| `/status/{job_id}` | GET | Kiểm tra trạng thái job / Check job status |
| `/download/{job_id}` | GET | Tải kết quả / Download result |

### 2. Celery Application (app/celery_app.py)

**Vai trò / Role**: Cấu hình Celery để xử lý background tasks

**Chức năng / Functions**:
- Kết nối đến Redis broker
- Cấu hình serialization (JSON)
- Định tuyến tasks vào queues
- Quản lý timezone và retry logic

**Cấu hình quan trọng / Important config**:
```python
- broker: Redis URL - nơi chứa queue
- backend: Redis URL - nơi lưu kết quả
- task_serializer: "json" - format serialize
- task_routes: Định tuyến tasks
```

### 3. Celery Tasks (app/tasks.py)

**Vai trò / Role**: Định nghĩa các background tasks

**Chức năng / Functions**:
- Task `remove_background_task`: Xóa background từ ảnh
- Cập nhật job status trong Redis
- Retry khi thất bại (max 3 lần)
- Lưu kết quả vào disk
- Dọn dẹp files tạm

**Flow xử lý / Processing flow**:
```
1. PENDING → Worker nhận task
2. PROCESSING → Đang xử lý
3. DONE/FAILED → Hoàn thành hoặc thất bại
```

### 4. Redis Server

**Vai trò / Role**: Message broker và data store

**Chức năng / Functions**:
- **Message Broker**: Queue để gửi/nhận Celery tasks
- **Backend**: Lưu kết quả của tasks
- **Metadata Store**: Lưu thông tin job (status, paths, errors)

**Dữ liệu lưu trữ / Stored data**:
```json
{
  "job:{job_id}": {
    "status": "PENDING|PROCESSING|DONE|FAILED",
    "upload_path": "/path/to/upload.jpg",
    "result_path": "/path/to/result.png",
    "task_id": "celery-task-id",
    "error": "error message if failed"
  }
}
```

## Luồng xử lý / Processing Flows

### Flow 1: Đồng bộ (Synchronous) - `/remove`

```
Client → FastAPI → rembg.remove() → Response với ảnh kết quả
   ↓                                        ↑
   └────────────── ~2-5 giây ──────────────┘
```

**Ưu điểm / Advantages**:
- Đơn giản, trả về ngay
- Không cần poll status

**Nhược điểm / Disadvantages**:
- Có thể timeout với file lớn
- Block request cho đến khi xong
- Không scale tốt với nhiều requests

### Flow 2: Bất đồng bộ (Asynchronous) - `/remove-async`

```
1. Client → POST /remove-async
            ↓
2. FastAPI → Lưu file + tạo job_id
            ↓
3. FastAPI → Enqueue task vào Redis
            ↓
4. FastAPI → Trả về job_id ngay lập tức
            ↓
5. Client ← Response {"job_id": "xxx"}
            ↓
6. Worker → Pick task từ Redis queue
            ↓
7. Worker → Xử lý xóa background
            ↓
8. Worker → Lưu kết quả + cập nhật status
            ↓
9. Client → GET /status/{job_id} (poll)
            ↓
10. FastAPI → Đọc status từ Redis
            ↓
11. Client ← {"status": "DONE", "download_url": "..."}
            ↓
12. Client → GET /download/{job_id}
            ↓
13. FastAPI → Trả về file ảnh kết quả
```

**Ưu điểm / Advantages**:
- Không timeout
- Scale tốt (thêm workers)
- Xử lý được nhiều jobs đồng thời
- Client có thể làm việc khác trong khi chờ

**Nhược điểm / Disadvantages**:
- Phức tạp hơn
- Cần poll status
- Cần Redis infrastructure

## Biến môi trường / Environment Variables

| Biến | Mặc định | Mô tả / Description |
|------|----------|---------------------|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `DATA_DIR` | `/data` | Thư mục lưu uploads và results |
| `MAX_UPLOAD_MB` | `15` | Kích thước file tối đa (MB) |
| `LOG_LEVEL` | `INFO` | Mức độ logging (DEBUG, INFO, WARNING, ERROR) |
| `MODEL_PREWARM` | `1` | Pre-warm model lúc startup (1=yes, 0=no) |
| `CORS_ALLOW_ORIGINS` | `*` | CORS allowed origins (phân cách bằng dấu phẩy) |

## Cách deploy / How to Deploy

### Option 1: Docker Compose (Khuyên dùng / Recommended)

```bash
# Clone repo
git clone https://github.com/jdsalas065/jds.git
cd jds

# Start tất cả services
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Option 2: Manual (Development)

```bash
# 1. Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. Start Celery worker (terminal mới / new terminal)
celery -A app.celery_app worker --loglevel=info -Q rembg
```

## Best Practices / Thực hành tốt nhất

### 1. Security / Bảo mật
- [ ] Giới hạn `CORS_ALLOW_ORIGINS` trong production (không dùng `*`)
- [ ] Thêm authentication/authorization cho sensitive endpoints
- [ ] Validate và sanitize input
- [ ] Rate limiting để chống abuse
- [ ] HTTPS trong production

### 2. Performance / Hiệu năng
- [ ] Pre-warm model với `MODEL_PREWARM=1`
- [ ] Scale bằng cách thêm workers: `--concurrency=4`
- [ ] Cache results nếu có thể
- [ ] Giới hạn file size hợp lý
- [ ] Monitor với Prometheus metrics

### 3. Reliability / Độ tin cậy
- [ ] Implement health checks
- [ ] Retry logic cho tasks (đã có trong code)
- [ ] Graceful shutdown cho workers
- [ ] Backup Redis nếu data quan trọng
- [ ] Log đầy đủ để debug

### 4. Monitoring / Giám sát
- [ ] Xem `/metrics` endpoint với Prometheus
- [ ] Track request count, latency
- [ ] Monitor queue length trong Redis
- [ ] Alert khi có failures nhiều
- [ ] Dashboard với Grafana

## Mở rộng / Extending

### Thêm endpoint mới / Adding new endpoints

```python
# Trong app/main.py
@app.post("/your-endpoint")
async def your_function(data: YourModel):
    """
    Mô tả endpoint
    Endpoint description
    """
    # Xử lý logic
    return {"result": "data"}
```

### Thêm Celery task mới / Adding new Celery tasks

```python
# Trong app/tasks.py
@celery_app.task(name="app.tasks.your_task", bind=True)
def your_task(self, arg1, arg2):
    """
    Mô tả task
    Task description
    """
    # Xử lý
    return result
```

### Thêm middleware / Adding middleware

```python
# Trong app/main.py
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["example.com", "*.example.com"]
)
```

## Chiến lược Scale / Scaling Strategies

### Khi nào cần scale? / When to scale?

Cần scale khi gặp các dấu hiệu sau:
- Request latency tăng cao
- Queue length trong Redis ngày càng dài
- CPU/Memory usage cao liên tục
- Có nhiều API endpoints và tasks hơn

### 1. Scale Horizontal - Thêm instances / Add more instances

#### Cấu trúc hiện tại (Đơn giản - Simple)
```
┌─────────────┐
│  FastAPI    │  1 instance
└─────────────┘
       │
┌─────────────┐
│   Redis     │  1 instance
└─────────────┘
       │
┌─────────────┐
│  Celery     │  1 worker
│  Worker     │
└─────────────┘
```

#### Cấu trúc khi scale (Recommended for production)
```
                    ┌──────────────┐
                    │ Load Balancer│
                    │  (Nginx/ALB) │
                    └──────┬───────┘
                           │
        ┏━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━┓
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  FastAPI #1  │  │  FastAPI #2  │  │  FastAPI #3  │
└──────────────┘  └──────────────┘  └──────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                  ┌─────────────────┐
                  │  Redis Cluster  │
                  │  (HA setup)     │
                  └────────┬────────┘
                           │
        ┏━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━┓
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Worker #1   │  │  Worker #2   │  │  Worker #3   │
│  (Queue: A)  │  │  (Queue: B)  │  │  (Queue: C)  │
└──────────────┘  └──────────────┘  └──────────────┘
```

**Cách thực hiện / How to implement:**

```bash
# Scale FastAPI với Docker Compose
docker-compose up --scale api=3

# Scale Celery workers
docker-compose up --scale worker=5

# Hoặc chạy workers riêng biệt với queues khác nhau
celery -A app.celery_app worker -Q queue1 --concurrency=4
celery -A app.celery_app worker -Q queue2 --concurrency=4
celery -A app.celery_app worker -Q queue3 --concurrency=4
```

### 2. Tổ chức lại code khi có nhiều APIs / Reorganize code with many APIs

#### Cấu trúc hiện tại (Tất cả trong 1 file - All in one file)
```
app/
├── main.py           # Tất cả endpoints ở đây (All endpoints here)
├── celery_app.py
└── tasks.py          # Tất cả tasks ở đây (All tasks here)
```

**Vấn đề / Problems:**
- File `main.py` sẽ rất dài và khó maintain
- Khó phân chia công việc cho team
- Khó test từng module riêng

#### Cấu trúc nên dùng (Module hóa - Modular)
```
app/
├── __init__.py
├── main.py                    # Application setup only
├── core/
│   ├── __init__.py
│   ├── config.py             # Configuration
│   ├── dependencies.py       # Shared dependencies
│   └── security.py           # Auth, CORS, etc.
├── api/
│   ├── __init__.py
│   ├── v1/                   # API version 1
│   │   ├── __init__.py
│   │   ├── endpoints/
│   │   │   ├── __init__.py
│   │   │   ├── images.py     # Image-related endpoints
│   │   │   ├── users.py      # User-related endpoints
│   │   │   └── jobs.py       # Job-related endpoints
│   │   └── router.py         # Router cho v1
│   └── v2/                   # API version 2 (future)
│       └── ...
├── models/
│   ├── __init__.py
│   ├── image.py              # Pydantic models cho images
│   ├── user.py               # Pydantic models cho users
│   └── job.py                # Pydantic models cho jobs
├── services/
│   ├── __init__.py
│   ├── image_service.py      # Business logic cho images
│   ├── user_service.py       # Business logic cho users
│   └── job_service.py        # Business logic cho jobs
├── workers/
│   ├── __init__.py
│   ├── celery_app.py         # Celery config
│   └── tasks/
│       ├── __init__.py
│       ├── image_tasks.py    # Image processing tasks
│       ├── email_tasks.py    # Email sending tasks
│       └── report_tasks.py   # Report generation tasks
├── db/
│   ├── __init__.py
│   ├── database.py           # Database connection
│   └── repositories/
│       ├── __init__.py
│       ├── image_repo.py
│       └── user_repo.py
└── utils/
    ├── __init__.py
    ├── validators.py
    └── helpers.py
```

**Ví dụ main.py mới / Example new main.py:**

```python
from fastapi import FastAPI
from app.core.config import settings
from app.core.dependencies import setup_middleware
from app.api.v1.router import api_router as v1_router
from app.api.v2.router import api_router as v2_router

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

# Setup middleware
setup_middleware(app)

# Include routers theo version
app.include_router(v1_router, prefix="/api/v1")
app.include_router(v2_router, prefix="/api/v2")

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Ví dụ endpoint file / Example endpoint file:**

```python
# app/api/v1/endpoints/images.py
from fastapi import APIRouter, File, UploadFile, Depends
from app.services.image_service import ImageService
from app.models.image import ImageResponse

router = APIRouter()

@router.post("/remove", response_model=ImageResponse)
async def remove_background(
    file: UploadFile = File(...),
    service: ImageService = Depends()
):
    """Xóa background đồng bộ / Sync background removal"""
    return await service.remove_background_sync(file)

@router.post("/remove-async", response_model=dict)
async def remove_background_async(
    file: UploadFile = File(...),
    service: ImageService = Depends()
):
    """Xóa background bất đồng bộ / Async background removal"""
    return await service.remove_background_async(file)
```

### 3. Tách Celery queues theo loại tasks / Separate Celery queues by task type

**Cấu trúc hiện tại (1 queue - Single queue):**
```python
# Tất cả tasks vào 1 queue "rembg"
task_routes = {
    "app.tasks.remove_background_task": {"queue": "rembg"},
}
```

**Cấu trúc nên dùng (Multiple queues):**
```python
# app/workers/celery_app.py
task_routes = {
    # Queue cho image processing (priority cao)
    "app.workers.tasks.image_tasks.remove_background": {"queue": "images_high"},
    "app.workers.tasks.image_tasks.resize_image": {"queue": "images_low"},
    
    # Queue cho email (priority thấp)
    "app.workers.tasks.email_tasks.send_email": {"queue": "emails"},
    
    # Queue cho reports (có thể chạy lâu)
    "app.workers.tasks.report_tasks.generate_report": {"queue": "reports"},
    
    # Queue cho cleanup (chạy định kỳ)
    "app.workers.tasks.cleanup_tasks.delete_old_files": {"queue": "maintenance"},
}
```

**Chạy workers chuyên biệt / Run specialized workers:**
```bash
# Worker cho image processing (nhiều resources)
celery -A app.workers.celery_app worker -Q images_high -c 4 --max-tasks-per-child=10

# Worker cho emails (ít resources)
celery -A app.workers.celery_app worker -Q emails -c 2

# Worker cho reports (chạy lâu, ít concurrency)
celery -A app.workers.celery_app worker -Q reports -c 1 --time-limit=3600

# Worker xử lý nhiều queues (flexible)
celery -A app.workers.celery_app worker -Q images_low,emails,maintenance -c 2
```

### 4. Thêm Database khi scale / Add Database when scaling

**Hiện tại:** Dùng Redis để lưu job metadata (tạm thời)

**Khi scale:** Nên dùng database riêng (PostgreSQL, MongoDB) để:
- Lưu trữ lâu dài (persistent storage)
- Query phức tạp (complex queries)
- Relationship giữa entities
- Audit logs

**Cấu trúc với Database:**
```
┌──────────────┐
│   FastAPI    │
└──────┬───────┘
       │
       ├─────────► Redis (Cache + Session)
       │
       ├─────────► PostgreSQL (Main data)
       │           • Users
       │           • Jobs history
       │           • Files metadata
       │           • Audit logs
       │
       └─────────► S3/MinIO (File storage)
                   • Uploaded files
                   • Processed results
```

### 5. Rate Limiting và Caching

```python
# Thêm rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/remove")
@limiter.limit("10/minute")  # 10 requests per minute
async def remove_background(request: Request, file: UploadFile = File(...)):
    ...

# Thêm caching với Redis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

@cache(expire=3600)  # Cache 1 hour
@app.get("/status/{job_id}")
async def get_status(job_id: str):
    ...
```

### 6. Monitoring và Observability khi scale

```python
# Thêm distributed tracing với OpenTelemetry
from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Setup tracing
trace.set_tracer_provider(TracerProvider())
jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)

# Thêm structured logging
import structlog

logger = structlog.get_logger()
logger.info("processing_job", job_id=job_id, user_id=user_id)
```

### 7. API Versioning

```python
# Hỗ trợ nhiều versions của API
app.include_router(v1_router, prefix="/api/v1", tags=["v1"])
app.include_router(v2_router, prefix="/api/v2", tags=["v2"])

# Hoặc dùng header-based versioning
@app.middleware("http")
async def api_version_middleware(request: Request, call_next):
    version = request.headers.get("API-Version", "v1")
    request.state.api_version = version
    response = await call_next(request)
    return response
```

### Tóm tắt thay đổi khi scale / Summary of changes when scaling

| Aspect | Hiện tại / Current | Khi scale / When scaling |
|--------|-------------------|-------------------------|
| **Code Structure** | 1 file main.py | Modules: api/, services/, workers/ |
| **API Organization** | Tất cả endpoints trong 1 file | Tách theo feature + versioning |
| **Workers** | 1 worker, 1 queue | Multiple workers, multiple queues |
| **Storage** | Redis only | Redis + Database + Object Storage |
| **Scaling** | Vertical (tăng resources) | Horizontal (thêm instances) |
| **Monitoring** | Prometheus basic | Prometheus + Grafana + Tracing |
| **Caching** | Không có | Redis caching layer |
| **Rate Limiting** | Không có | Rate limiting per user/IP |
| **Load Balancing** | Không có | Nginx/ALB load balancer |
| **Database** | Không có | PostgreSQL/MongoDB |
| **Auth** | Không có | JWT/OAuth2 authentication |

### Migration path từ cấu trúc hiện tại / Migration from current structure

**Bước 1:** Tách endpoints ra thành modules (không breaking changes)
**Bước 2:** Thêm database để lưu metadata
**Bước 3:** Tách workers thành nhiều queues
**Bước 4:** Thêm load balancer và scale horizontal
**Bước 5:** Thêm caching, rate limiting, monitoring
**Bước 6:** Implement API versioning

Có thể làm từng bước một mà không cần refactor toàn bộ cùng lúc!

## Tài liệu tham khảo / References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Celery Documentation](https://docs.celeryq.dev/)
- [Redis Documentation](https://redis.io/docs/)
- [rembg Library](https://github.com/danielgatis/rembg)
- [Prometheus Python Client](https://github.com/prometheus/client_python)

## License

MIT
