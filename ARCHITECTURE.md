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

## Tài liệu tham khảo / References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Celery Documentation](https://docs.celeryq.dev/)
- [Redis Documentation](https://redis.io/docs/)
- [rembg Library](https://github.com/danielgatis/rembg)
- [Prometheus Python Client](https://github.com/prometheus/client_python)

## License

MIT
