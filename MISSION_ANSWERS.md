# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong mã nguồn & in secret ra log (Dòng 17–18, 34):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` nằm ngay trong file `.py`, thậm chí dòng 34 còn `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi push code lên Git hoặc thu thập log tập trung, toàn bộ khóa bí mật bị lộ ngay lập tức.
   - *Cách `production/` sửa:* Đọc toàn bộ cấu hình qua biến môi trường `os.getenv(...)` trong `production/config.py` (dòng 17–35) và tuyệt đối không ghi secret ra log (`production/app.py` dòng 111–115 chỉ log `question_length`).
2. **Không quản lý cấu hình theo môi trường & bật cứng `DEBUG = True` (Dòng 21–22):**
   - `DEBUG = True` và `MAX_TOKENS = 500` bị gán cứng, vi phạm nguyên tắc *12-Factor III (Store config in the environment)* — muốn đổi cấu hình giữa dev/staging/prod phải sửa code.
3. **Dùng `print()` thay vì Structured Logging (Dòng 33, 34, 38, 48):**
   - Không có mức độ nghiêm trọng (`INFO`, `WARNING`, `ERROR`), không có timestamp chuẩn UTC và không ở định dạng JSON nên các hệ thống tập trung log (Loki, ELK, Cloud Logging) không thể parse và truy vấn theo trường.
   - *Cách `production/` sửa:* Cấu hình `logging` xuất chuỗi JSON hợp lệ gồm `time`, `level`, `msg` và metadata sự kiện (`production/app.py` dòng 28–31, 49–55).
4. **Thiếu Health Check (`/health`) và Readiness Probe (`/ready`) (Dòng 42–43):**
   - Nền tảng cloud (Railway, Render, Kubernetes) không biết container còn sống hay đã treo để tự khởi động lại, và Load Balancer không biết instance đã khởi tạo xong chưa trước khi đẩy traffic vào.
   - *Cách `production/` sửa:* Bổ sung `GET /health` (dòng 135) và `GET /ready` trả `503` khi `is_ready == False` (dòng 152–161).
5. **Bind cứng `host="localhost"`, cố định `port=8000` và bật `reload=True` (Dòng 50–53):**
   - `host="localhost"` chỉ nhận kết nối loopback bên trong container nên không thể truy cập từ bên ngoài Docker/Cloud; `port=8000` cố định sẽ lỗi trên Railway/Render vốn cấp biến `PORT` động; `reload=True` chạy file watcher gây tốn tài nguyên và mất ổn định ở production.
   - *Cách `production/` sửa:* Bind `0.0.0.0`, đọc `PORT` từ biến môi trường và chỉ bật `reload` khi `settings.debug` là `True` (`production/app.py` dòng 194–199).
6. **Không xử lý Graceful Shutdown (Thiếu `lifespan` và `SIGTERM` handler):**
   - Khi nền tảng dừng hoặc cập nhật phiên bản mới, container bị tắt đột ngột làm đứt ngang các request khách hàng đang chờ phản hồi.
   - *Cách `production/` sửa:* Dùng `@asynccontextmanager async def lifespan(app)` kết hợp bắt tín hiệu `signal.SIGTERM` (`production/app.py` dòng 39–68, 180–189).
7. **Không kiểm tra đầu vào JSON & không giới hạn CORS:**
   - Bản `develop` nhận `question: str` qua query string mà không kiểm tra rỗng hay độ dài tối đa, trong khi `production/app.py` kiểm tra JSON body (trả `422` khi thiếu `question`) và cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS`.

---

### Exercise 1.2: Kết quả chạy thử bản `develop`

Khi gửi JSON body vào bản `develop`, FastAPI báo lỗi `422` vì hàm `def ask_agent(question: str)` mặc định đọc `question` từ query string:

```http
$ curl -i -X POST "http://localhost:8000/ask" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 422 Unprocessable Entity
date: Wed, 25 Nov 2026 07:52:23 GMT
server: uvicorn
content-length: 94
content-type: application/json

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Gọi đúng qua query parameter `?question=Hello` trả về `200 OK`:

```http
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:52:23 GMT
server: uvicorn
content-length: 126
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Tiêu chí | Bản `develop` | Bản `production` | Tại sao quan trọng trong thực tế? |
|---|---|---|---|
| **Quản lý Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True` trong `app.py` | Đọc qua `os.getenv()` trong `config.py` kèm hàm `.validate()` fail-fast | Tránh lộ khoá bí mật trên Git; dùng chung một artifact image cho nhiều môi trường (dev/staging/prod) mà không phải sửa code. |
| **Health & Readiness Check** | Không có | Tách riêng `GET /health` (liveness) và `GET /ready` (readiness trả `503` khi chưa sẵn sàng) | Giúp orchestrator tự động restart khi process treo và giúp Load Balancer ngừng điều phối traffic vào instance đang khởi động/tắt. |
| **Logging** | `print()` tự do, in cả API key ra màn hình | Structured JSON logging, ẩn toàn bộ dữ liệu nhạy cảm | Log JSON một dòng giúp hệ thống giám sát tự động đánh chỉ mục, lọc sự cố và tạo cảnh báo mà không làm rò rỉ thông tin nhạy cảm. |
| **Network Binding & Port** | `host="localhost"`, cứng `port=8000`, `reload=True` | `host="0.0.0.0"`, đọc động biến `PORT`, tắt `reload` ở prod | Container trên Cloud chỉ nhận được kết nối ngoài qua `0.0.0.0` trên cổng do nền tảng cấp phát động (`$PORT`). |
| **Graceful Shutdown** | Tắt ngang ngay lập tức khi nhận tín hiệu dừng | Quản lý vòng đời qua `lifespan` + xử lý `SIGTERM`, hạ cờ `is_ready = False` | Đảm bảo zero-downtime khi rolling deploy: ngừng nhận request mới nhưng vẫn hoàn tất các request đang xử lý dở. |
| **CORS & Validation** | Không giới hạn origin, nhận query param thô | `CORSMiddleware` theo `ALLOWED_ORIGINS`, kiểm tra body hợp lệ (`422`) | Ngăn trình duyệt từ tên miền lạ gọi trái phép và chặn dữ liệu rác trước khi tiêu tốn chi phí gọi LLM. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` — bản phân phối Python đầy đủ dựa trên Debian (chứa sẵn trình biên dịch C, thư viện hệ thống, header dev… nên dung lượng rất lớn, khoảng ~1 GB).
2. **Working directory là gì?**
   - `/app` (đặt bởi lệnh `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối tại thư mục này bên trong container.
3. **Tại sao phải `COPY requirements.txt` và `RUN pip install` trước khi `COPY app.py`?**
   - Để tận dụng **Docker Layer Caching**. Docker cache từng chỉ thị thành một layer bất biến; khi sửa mã nguồn `app.py` (diễn ra thường xuyên) nhưng không đổi `requirements.txt` (ít thay đổi), Docker tái sử dụng ngay layer đã cài đặt thư viện thay vì tải và cài lại `pip install` từ đầu, rút ngắn thời gian build từ vài phút xuống vài giây.
4. **`CMD` khác `ENTRYPOINT` như thế nào?**
   - `ENTRYPOINT` cố định chương trình thực thi chính của container (các đối số truyền thêm qua `docker run <image> <args>` sẽ được nối tiếp làm tham số cho `ENTRYPOINT`).
   - `CMD` cung cấp lệnh mặc định (hoặc tham số mặc định cho `ENTRYPOINT`) và **bị ghi đè hoàn toàn** nếu người dùng truyền lệnh khác ở cuối `docker run <image> <other_cmd>`. Ngoài ra, nên dùng *exec form* `["uvicorn", ...]` thay vì *shell form* để tiến trình chính nhận trực tiếp tín hiệu `SIGTERM` ở PID 1.

---

### Exercise 2.2 & 2.3: Multi-stage Build & So sánh dung lượng Image

- **Phân tích `02-docker/production/Dockerfile`:**
  - **Stage 1 (`builder` — `FROM python:3.11-slim AS builder`):** Cài đặt các gói phục vụ biên dịch (`gcc`, `libpq-dev`) và cài toàn bộ Python packages vào `/root/.local` (`pip install --no-cache-dir --user`). Toàn bộ trình biên dịch và cache apt ở stage này bị loại bỏ, không đi vào image cuối.
  - **Stage 2 (`runtime` — `FROM python:3.11-slim AS runtime`):** Bắt đầu từ image `slim` sạch, tạo tài khoản không đặc quyền `appuser` (`USER appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn cần chạy, bổ sung `HEALTHCHECK` và chạy `uvicorn` với 2 workers.
- **Kết quả chạy & gọi container `my-agent:develop` (Exercise 2.2):**

```http
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

- **Kích thước đo thực tế bằng `docker images` (Exercise 2.3):**

```text
$ docker images my-agent --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
REPOSITORY   TAG        SIZE
my-agent     develop    1.67GB
my-agent     advanced   240MB
```

  - `my-agent:develop` (base `python:3.11` single-stage): **1.67 GB** (`1,590.5 MiB` / `1,667,779,815 bytes`)
  - `my-agent:advanced` (base `python:3.11-slim` multi-stage): **240 MB** (`228.7 MiB` / `239,815,213 bytes`)
  - **Chênh lệch giảm:** **85.6%** (tiết kiệm ~1.43 GB / image nhờ dùng base `slim` và bỏ toàn bộ compiler/build tools ở stage `builder`).

---

### Exercise 2.4: Sơ đồ kiến trúc Docker Compose Stack (`02-docker/production/docker-compose.yml`)

Stack khởi tạo **4 services** giao tiếp cô lập bên trong mạng nội bộ `internal` (bridge network), chỉ mở cổng HTTP/HTTPS tại lớp Reverse Proxy Nginx:

```text
                        ┌──────────────────────────────────────────────────────┐
                        │               Docker Bridge: internal                │
┌──────────┐  :80/:443  │  ┌───────────────┐      :8000      ┌──────────────┐  │
│  Client  │ ─────────► │  │     nginx     │ ──────────────► │    agent     │  │
└──────────┘            │  │ (nginx:alpine)│  proxy_pass +   │  (FastAPI x2 │  │
                        │  │ rate: 10 req/s│  health route   │   workers)   │  │
                        │  └───────────────┘                 └───┬──────┬───┘  │
                        │                                        │      │      │
                        │               REDIS_URL (:6379) ───────┘      │      │
                        │               ▼                               │      │
                        │        ┌──────────────┐   QDRANT_URL (:6333)  │      │
                        │        │    redis     │   ▼                   │      │
                        │        │(7-alpine LRU)│  ┌────────────────┐   │      │
                        │        └──────┬───────┘  │     qdrant     │◄──┘      │
                        │               │          │   (v1.9.0)     │          │
                        └───────────────┼──────────┼────────────────┼──────────┘
                                        ▼          ▼
                              [redis_data vol]  [qdrant_data vol]
```

- **Cách giao tiếp:**
  - Client bên ngoài chỉ gọi được `nginx` ở cổng `80`/`443` (`agent`, `redis`, `qdrant` không publish port ra host, giảm bề mặt tấn công).
  - `nginx` áp dụng giới hạn tốc độ `10r/s` (`burst=20`), gắn security headers (`X-Frame-Options`, `X-Content-Type-Options`) và chuyển tiếp request tới `http://agent:8000` qua Docker DNS nội bộ.
  - `agent` chỉ khởi động sau khi cả `redis` và `qdrant` đều đạt trạng thái `service_healthy`, kết nối qua `redis://redis:6379/0` và `http://qdrant:6333`.

- **Kết quả test thực tế qua Nginx (`http://localhost`):**

```http
$ curl http://localhost/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.2,"version":"2.0.0","timestamp":"2026-11-25T08:15:00.847730"}

$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1: Triển khai Agent Part 6 lên Cloud

- **Thư mục triển khai:** `06-lab-complete/` (sử dụng trực tiếp image build từ `06-lab-complete/Dockerfile` và dịch vụ Redis trên Cloud).
- **Public URL:** *(Điền URL nhận từ `railway domain` hoặc Render Dashboard — đồng bộ với `DEPLOYMENT.md`)*
- **Ảnh chụp minh chứng:**
  - Dashboard dịch vụ: [screenshots/dashboard.png](screenshots/dashboard.png)
  - Trạng thái container/logs đang chạy: [screenshots/running.png](screenshots/running.png)
  - Kết quả kiểm tra 4 lệnh HTTP (`200`, `200`, `401`, `200`): [screenshots/test.png](screenshots/test.png)

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Khía cạnh | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| **Định dạng & Phạm vi** | File cấu hình định dạng **TOML** áp dụng cho **từng service đơn lẻ** nằm trong thư mục deploy. | File Infrastructure-as-Code định dạng **YAML** mô tả **toàn bộ kiến trúc đa dịch vụ** (cả web service lẫn managed Redis `type: redis`) trong một lần đồng bộ Blueprint. |
| **Cơ chế Build & Runtime** | Chọn builder (`DOCKERFILE`, `NIXPACKS`, `RAILPACK`) trong block `[build]`; Railway tự phát hiện `Dockerfile` và truyền động `$PORT`. | Khai báo rõ `runtime: python` (kèm `buildCommand` + `startCommand`) hoặc `runtime: docker` kèm `plan`, `region` cụ thể cho từng tài nguyên. |
| **Quản lý Biến môi trường & Secret** | Không khai báo danh sách env/secret trong `railway.toml`; quản lý tách biệt qua Railway CLI (`railway variables set`) hoặc Dashboard để tránh lộ secret. | Khai báo trực tiếp danh sách `envVars` ngay trong YAML; với biến nhạy cảm dùng `sync: false` (nhập tay trên Dashboard) hoặc `generateValue: true` (tự sinh ngẫu nhiên), và hỗ trợ nối tự động chuỗi kết nối nội bộ qua `fromService` (ví dụ lấy `connectionString` từ Redis). |
| **Chính sách Phục hồi (Resilience)** | Cấu hình chi tiết ngay trong `[deploy]`: `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries`. | Khai báo `healthCheckPath: /health` và `autoDeploy: true` khi có commit mới trên nhánh GitHub liên kết. |

---

### Exercise 3.3: Mô tả Pipeline CI/CD GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Khi có code mới đẩy lên nhánh chính, Google Cloud Build thực thi tuần tự 4 bước tự động trong `cloudbuild.yaml`:
1. **`test` (`python:3.11-slim`):** Cài đặt dependencies từ `requirements.txt` cùng `pytest` và chạy bộ kiểm thử tự động `pytest tests/ -v`; nếu test lỗi thì dừng ngay toàn bộ pipeline, không build image.
2. **`build` (`docker`, `waitFor: [test]`):** Build Docker image gắn đồng thời 2 tag (`:$COMMIT_SHA` để truy vết phiên bản chính xác và `:latest`), tận dụng `--cache-from` từ image `:latest` trước đó để tăng tốc độ build.
3. **`push` (`docker`, `waitFor: [build]`):** Đẩy toàn bộ image tags vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy` (`gcloud run deploy`, `waitFor: [push]`):** Triển khai bản image `:$COMMIT_SHA` lên Cloud Run tại region `asia-southeast1` (tương ứng cấu hình Knative trong `service.yaml`): giới hạn tài nguyên `1 CPU / 512Mi RAM`, `containerConcurrency: 80`, giữ `min-instances=1` để chống cold-start và scale tối đa `max-instances=10`, tiêm secret an toàn từ **Secret Manager** (`--set-secrets` / `secretKeyRef`) và giám sát sức khoẻ container bằng `startupProbe` (`/ready`) kết hợp `livenessProbe` (`/health`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

- **API key được kiểm tra ở đâu?** Kiểm tra tại dependency `verify_api_key` (`04-api-gateway/develop/app.py` dòng 39–54) thông qua `APIKeyHeader(name="X-API-Key", auto_error=False)`, được gắn vào endpoint `POST /ask` bằng `_key: str = Depends(verify_api_key)`, trong khi `/` và `/health` vẫn để public cho nền tảng kiểm tra.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Trong bản `04-api-gateway/develop/app.py`, thiếu header trả `401 Unauthorized`, sai giá trị key trả `403 Forbidden` (lưu ý ở chuẩn hợp đồng Part 6 thì cả thiếu lẫn sai key đều thống nhất trả `401`).
- **Làm sao để rotate key không gây downtime?** Đọc danh sách nhiều key hợp lệ cách nhau bởi dấu phẩy trong biến môi trường (ví dụ `AGENT_API_KEYS="new_key_v2,old_key_v1"`): bước 1 thêm `new_key_v2` song song với `old_key_v1`, bước 2 cập nhật các client chuyển sang `new_key_v2`, bước 3 xoá `old_key_v1` khỏi cấu hình và khởi động lại/reload dịch vụ.

**Kết quả chạy thực tế (`AGENT_API_KEY=secret-key-123`):**

```http
# 1. Không gửi X-API-Key → 401 Unauthorized
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:52:25 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2. Gửi đúng X-API-Key → 200 OK
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:52:25 GMT
server: uvicorn
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Phân tích `rate_limiter.py`:**
  - **Thuật toán:** *Sliding Window Log / Counter* (lưu hàng đợi `deque` chứa các mốc thời gian `timestamp` của từng user, mỗi lần kiểm tra sẽ loại bỏ các timestamp nhỏ hơn `now - 60` giây rồi đếm số phần tử còn lại).
  - **Ngưỡng giới hạn:** Tài khoản role `user` (`student`) giới hạn **10 requests/phút** (`rate_limiter_user`); tài khoản role `admin` (`teacher`) được ưu tiên **100 requests/phút** (`rate_limiter_admin`). Để mở rộng hoặc bypass cho `admin` trong thực tế, ứng dụng kiểm tra claim `role == "admin"` đã ký số bên trong JWT payload trước khi áp bộ đếm.

**Kết quả test thực tế `401` / `200` / `429` (đã che JWT token):**

```http
# 1. Gọi POST /ask không có Bearer token → 401 Unauthorized
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 07:52:27 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 2. Đăng nhập tài khoản student / demo123 tại POST /auth/token → 200 OK
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:52:27 GMT
server: uvicorn
content-length: 307
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"<REDACTED_JWT_TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED_PREFIX>..."}

# 3. Gọi vòng lặp với Bearer token: Request #1 thành công → 200 OK
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" -H "Content-Type: application/json" -d '{"question": "Test 1"}'
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:52:27 GMT
server: uvicorn
content-length: 179
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Test 1","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

# 4. Tiếp tục vòng lặp tới Request #11 (vượt ngưỡng 10 req/phút của student) → 429 Too Many Requests
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" -H "Content-Type: application/json" -d '{"question": "Test 11"}'
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 07:52:29 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593209
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

---

### Exercise 4.4: Thiết kế Cost Guard & Lý do cần kết hợp cả Rate Limit lẫn Cost Guard

- **Vì sao cần cả hai?**
  - **Rate Limit** bảo vệ **tốc độ truy cập & năng lực xử lý hạ tầng** (chống DDoS/burst làm nghẽn worker), nhưng không kiểm soát được độ lớn của từng request (một user gửi đúng 10 req/phút nhưng mỗi request nhồi hàng chục nghìn token context vẫn đốt cạn tiền API).
  - **Cost Guard** bảo vệ trực tiếp **ngân sách tài chính** theo lượng token thực tế tiêu thụ (`input_tokens * đơn_giá_in + output_tokens * đơn_giá_out`).
- **Cách triển khai Cost Guard chuẩn Production với Redis (đã áp dụng vào Part 6 `app/cost_guard.py`):**
  1. Đặt key theo khung thời gian UTC: `cost:daily:YYYY-MM-DD` (TTL 2 ngày) và `cost:monthly:YYYY-MM` (TTL 35 ngày) trong Redis để mọi worker/instance dùng chung một sổ cái chi phí và tự động reset sang ngày/tháng mới.
  2. **Trước khi gọi LLM (`check_budget`):** Đọc tổng tiền hiện tại bằng `MGET`; nếu `daily_spent >= DAILY_BUDGET_USD` hoặc `monthly_spent >= MONTHLY_BUDGET_USD` thì chặn ngay và trả mã `HTTP 402 Payment Required`.
  3. **Sau khi gọi LLM (`record_cost`):** Tính chi phí thực tế của lượt gọi dựa trên số lượng input/output tokens và cộng nguyên tử vào Redis bằng lệnh `INCRBYFLOAT` kèm `EXPIRE` trong pipeline.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Sự khác biệt giữa Liveness (`/health`) và Readiness (`/ready`)

- **`GET /health` (Liveness Probe — "Process còn sống không?"):**
  - Chỉ kiểm tra bản thân tiến trình web server còn phản hồi không, **không phụ thuộc vào dịch vụ ngoài như Redis/DB**. Nếu `/health` thất bại, nền tảng sẽ `restart` lại container.
- **`GET /ready` (Readiness Probe — "Instance đã sẵn sàng xử lý request chưa?"):**
  - Kiểm tra đầy đủ các kết nối phụ thuộc (như `redis.ping()`). Khi Redis tạm thời chập chờn hoặc mất kết nối, `/ready` trả `503 Service Unavailable` để Load Balancer tạm ngưng gửi traffic vào instance đó, **nhưng `/health` vẫn phải trả `200`** để tránh việc orchestrator giết và khởi động lại hàng loạt container vô ích (cascading restart storm).

### Exercise 5.2: Cơ chế Graceful Shutdown

- Khi scale-in hoặc cập nhật phiên bản mới, container nhận tín hiệu `SIGTERM` từ Docker/Kubernetes (trước khi bị cưỡng bức bằng `SIGKILL` sau khoảng thời gian grace period 10–30s).
- Ứng dụng phải: (1) chạy uvicorn ở **PID 1** (`exec uvicorn ...`) để nhận trực tiếp `SIGTERM`, (2) ngừng nhận kết nối mới, (3) chờ các request LLM đang xử lý dở hoàn tất và trả mã `200`, (4) đóng kết nối thông qua context `lifespan` rồi thoát êm với `exit code 0`.

### Exercise 5.3 – 5.5: Thiết kế Stateless & Load Balancing 3 Instances với Nginx + Redis

- **Tại sao lưu state trong RAM bị hỏng khi scale nhiều instances?**
  - Mỗi container/worker là một không gian bộ nhớ độc lập. Khi chạy `--scale agent=3` sau Nginx round-robin (`upstream agent_cluster`), Request 1 của khách rơi vào `Instance A` (lưu lịch sử hội thoại hoặc bộ đếm rate-limit trong dict RAM của A), nhưng Request 2 được Nginx điều phối sang `Instance B` — `Instance B` có RAM trống nên mất toàn bộ ngữ cảnh hội thoại và đếm lại rate-limit từ đầu.
- **Giải pháp Stateless trong `05-scaling-reliability/production/`:**
  - Toàn bộ session hội thoại (`session:<session_id>`) được đọc/ghi tập trung trên **Redis** kèm TTL (`SETEX 3600s`). Bất kể Nginx phân phối request vào instance nào trong 3 replicas (thậm chí khi 1 instance bị tắt đột ngột, Nginx tự failover nhờ `proxy_next_upstream error timeout http_503`), lịch sử hội thoại của người dùng vẫn liền mạch 100%.
- **Kết quả chạy thực tế `test_stateless.py` trên stack `k5-day14-scaling` (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`, cổng `8080`, endpoint `POST /chat`):**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 50193e47-8707-4417-9ab0-6502238386c5

Request 1: [instance-435a4e]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-73dab0]
  Q: Why do we need containers?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 3: [instance-808241]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-435a4e]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 5: [instance-73dab0]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-808241', 'instance-73dab0', 'instance-435a4e'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

- **Giải thích kết quả:** 5 câu hỏi liên tiếp trong cùng `session_id` được Nginx chia đều round-robin sang cả **3 instance khác nhau** (`instance-435a4e`, `instance-73dab0`, `instance-808241`). Khi gọi `GET /chat/{session_id}/history`, toàn bộ **10 messages (5 turns)** vẫn được bảo toàn nguyên vẹn vì mọi state đều đọc/ghi trực tiếp trên Redis dùng chung thay vì RAM cục bộ của từng container. Sau khi kiểm thử đã chạy `docker compose -p k5-day14-scaling down -v` để giải phóng cổng 8080.

---

## Part 6: Final Project — `check_production_ready.py` Output

Kết quả chạy đầy đủ trên môi trường POSIX (`os.name == "posix"`) kết nối Docker Engine `29.9.3` (image `273 MB < 500 MB`, `docker stop` exit code `0` trong `1.0s`, `SIGTERM` giữ request in-flight trả `200` và thoát với exit code `0`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

Theo quy định tại `RULES.md`, dưới đây là nhật ký sử dụng trợ lý AI trong quá trình thực hiện bài Lab:

1. **Phân tích đề bài, lộ trình Checkpoints và các lưu ý riêng của lớp K5:**
   - **Câu hỏi gửi AI:** Đọc `README.md` và các tài liệu liên quan để phân tích cấu trúc điểm và phương pháp làm tối ưu đến Bước 3.
   - **Nội dung nhận được:** Bản tóm tắt cơ cấu điểm (120 điểm thô), các lưu ý quan trọng của lớp K5 (làm trực tiếp trong `06-lab-complete/`, chạy kiểm tra `SIGTERM` trên môi trường POSIX/WSL2 + Docker Desktop, endpoint `/auth/token` với `student`/`demo123` ở Part 4, dùng `-p k5-day14-scaling` ở cổng `8080` cho Part 5, gộp deploy Part 3 và Part 6).
   - **Tự chỉnh sửa & kiểm tra:** Đối chiếu lại với `RUBRIC.md` và `SUBMISSION.md` để chuẩn bị đúng cấu trúc file ở thư mục gốc (`MISSION_ANSWERS.md`, `DEPLOYMENT.md`).
2. **Hỗ trợ tổng hợp kiến thức & kiểm thử thực nghiệm Part 1–5:**
   - **Câu hỏi gửi AI:** Hỗ trợ đối chiếu mã nguồn `develop/` và `production/` ở các phần 1, 2, 3, 4, 5 và chạy kiểm thử các endpoint local.
   - **Nội dung nhận được:** Phân tích chi tiết các anti-patterns ở Part 1, cơ chế layer cache & multi-stage build ở Part 2, so sánh `railway.toml` vs `render.yaml` và luồng Cloud Build ở Part 3, phân tích Rate Limiter / Cost Guard ở Part 4 và Stateless Redis ở Part 5.
   - **Tự chỉnh sửa & kiểm tra:** Chạy thực tế các server FastAPI của Part 1 và Part 4 để lấy đúng mã phản hồi HTTP (`422`, `200`, `401`, `429` kèm headers `Retry-After`) và ẩn JWT token trước khi đưa vào `MISSION_ANSWERS.md`.
3. **Hoàn thiện các mục `TODO` trong `06-lab-complete/` (Part 6):**
   - **Câu hỏi gửi AI:** Gợi ý triển khai các module `config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py` (sliding window sorted set trên Redis), `cost_guard.py` (lưu chi phí theo ngày/tháng trên Redis), `main.py` (JSON logging formatter, `/health`, `/ready`, exception handlers không lộ stack trace, `lifespan` graceful shutdown), cùng multi-stage `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `railway.toml`, `render.yaml`.
   - **Nội dung nhận được:** Mã nguồn hoàn chỉnh cho các file trong `06-lab-complete/` đảm bảo không ping Redis lúc import để container khởi động độc lập được và chạy `uvicorn` ở PID 1 qua `exec`.
   - **Tự chỉnh sửa & kiểm tra:** Chạy đầy đủ `python check_production_ready.py` trên môi trường POSIX + Docker Engine `29.9.3`, đạt `43/43 checks passed` và **`PASS 12/12`** (image 273 MB, stateless Redis sau restart trả `429`, `SIGTERM` giữ request đang chạy trả `200` và `docker stop` exit code `0` trong `1.0s`). Đồng thời tự chạy build image Part 2 (`1.67GB` → `240MB`, giảm `85.6%`) và `test_stateless.py` Part 5 trên 3 agent instances.
