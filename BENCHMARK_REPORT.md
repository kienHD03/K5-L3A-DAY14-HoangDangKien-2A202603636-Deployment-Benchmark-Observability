# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây đều lấy trực tiếp từ các file báo cáo trong `reports/`, `benchmark-results/` và ảnh chụp trong `screenshots/`.

**Họ tên:** Hoàng Đăng Kiên — 2A202603636  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 · 12 cores / 16GB RAM · Python 3.12.7 · Docker Desktop (Engine 29.9.3)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Đảm bảo 95% người dùng nhận phản hồi dưới nửa giây (cảm giác mượt trong tương tác chat), đồng thời khớp ngưỡng kiểm thử của `load_test.py` (`--slo-p95-ms 500`). |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để chịu được lỗi upstream ngẫu nhiên (~1% `MOCK_ERROR_RATE`) mà không gây cảnh báo giả, khớp `--slo-error-rate 0.02`. |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau tối ưu `100 %`) | Chặn deploy nếu chất lượng trả lời tụt dưới mức hữu dụng và bắt buộc `0 regression` so với phiên bản baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.0 Metrics & Cardinality (Exercise 7.1)

Từ kết quả `GET http://localhost:8002/metrics` sau khi gọi `POST /ask`:
- **Counter (chỉ tăng):** `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total`, `llm_cost_usd_total`.
- **Gauge (tăng/giảm theo trạng thái hiện tại):** `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0`.
- **Histogram (chia bucket để tính percentile):** `http_request_duration_seconds`, `llm_request_duration_seconds`, và metric mới bổ sung `agent_question_length_chars` (buckets: `20, 50, 100, 200, 500, 1000, 2000` ký tự).
- **Tại sao `observe_requests` dùng `route.path` thay vì `request.url.path`?** Nếu bot quét hàng nghìn đường dẫn lạ (`/wp-admin`, `/.env`, `/a1b2c3`...), dùng URL thật làm label sẽ tạo hàng nghìn time series mới (**high cardinality**), làm phình bộ nhớ RAM của Prometheus và chậm mọi câu truy vấn. Gán route template (`route.path` hoặc `"unmatched"`) giới hạn số lượng time series ở mức cố định, an toàn cho production.

### 2.1 Concurrency vs latency (agent v2, 300 requests, `MOCK_SLOW_RATE=0.03`)

*(Nguồn: `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json`)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.11 | 203.9 | 237.6 | 1707.5 | 1.33% | PASS |
| 10 | 39.46 | 199.0 | 471.9 | 1699.2 | 1.67% | PASS |
| 50 | 99.30 | 205.2 | 550.5 | 1703.6 | 1.00% | FAIL (`p95 > 500ms`) |
| 100 | 46.52 | 742.1 | 4187.4 | 4361.8 | 1.00% | FAIL (`p95 > 500ms`) |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency.
- Từ `c=1` lên `c=10`, RPS tăng gần tuyến tính (`4.11 → 39.46 req/s`, ~9.6×) vì 1 tiến trình uvicorn async xử lý song song tốt các tác vụ I/O chờ LLM, giữ `p50` ổn định quanh ~200ms và vẫn đạt SLO.
- Tới `c=50`, RPS đạt đỉnh cục bộ (`99.30 req/s`, chỉ tăng ~2.5× dù concurrency tăng 5×) nhưng `p95` đã vượt ngưỡng SLO (`550.5 ms > 500 ms`).
- Tới `c=100`, hệ thống bước vào vùng **bão hoà (saturation)** trên 1 worker/event loop: các request bắt đầu phải xếp hàng chờ xử lý và ghi log/xử lý socket, làm `p50` tăng vọt lên `742.1 ms`, `p95` vọt lên `4187.4 ms`, kéo ngược thông lượng RPS tụt xuống còn `46.52 req/s` (hiện tượng quá tải hàng đợi). Để chịu được mức concurrency cao này cần scale ngang nhiều instance sau Load Balancer.

### 2.2 Tail latency (agent v2, 300 requests, `concurrency=20`)

*(Nguồn: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 211.8 | 458.0 | 499.8 |
| 0.03 (mặc định) | 263.0 | 490.8 | 1697.4 |
| 0.1 | 333.5 | 1698.2 | 1734.7 |

**Nhận xét:**
- **`p99` và `p95` nhạy hơn rất nhiều so với `avg` đối với các request chậm bất thường (tail latency):**
  - Khi tăng `MOCK_SLOW_RATE` từ `0` lên `0.03` (chỉ 3% request chậm thêm ~1.5s), `avg` chỉ nhích nhẹ `+51.2 ms` (`211.8 → 263.0 ms`), trông rất bình thường, nhưng **`p99` nhảy vọt gấp 3.4 lần** (`499.8 → 1697.4 ms`).
  - Khi tăng lên `0.1` (10% request chậm, vượt ngưỡng 5% của p95), **`p95` nhảy vọt lên `1698.2 ms`** (vi phạm nghiêm trọng SLO `500 ms`), trong khi **`avg` chỉ mới `333.5 ms`** (vẫn nhỏ hơn `500 ms`).
- **Vì sao không đặt SLO theo average?** Giá trị trung bình bị 90–97% request nhanh kéo xuống nên che giấu hoàn toàn trải nghiệm tệ của nhóm người dùng bị chậm (tail users). Đặt SLO theo **p95 / p99** phản ánh trực tiếp trải nghiệm tệ nhất mà 5% hoặc 1% người dùng thực tế phải chịu.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` — 23 câu trong `golden_dataset.jsonl`, giữ nguyên dataset không chỉnh sửa)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.6 | 109.1 | 114.5 |
| Tổng cost (USD) | $0.000397 | $0.000762 | $0.000798 |
| Cost / câu đúng (USD) | $0.00039675 | $0.00003627 | $0.00003469 |
| Quality gate | FAIL | PASS | PASS (`--min-accuracy 1.0`, `0 regression`) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry kiến thức kích hoạt bởi `["jwt"]` giải thích sự khác nhau giữa API key tĩnh và JWT (token có chữ ký số, chứa thời gian hết hạn) vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry kiến thức kích hoạt bởi `["hpa", "kubernetes", "autoscal"]` giải thích Kubernetes HPA scale pod dựa trên CPU, memory hoặc custom metrics vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và `production/utils/mock_llm.py`). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng vs Chi phí:** So với `v1`, `v2` có thêm bước retrieval (RAG) nhúng tài liệu vào prompt nên số token trung bình mỗi câu tăng gần gấp đôi (`56.6 → 109.1`, sau khi sửa KB là `114.5` tokens/câu) và tổng chi phí tăng ~2× (`$0.000397 → $0.000798`). Tuy nhiên, accuracy nhảy vọt từ `4.35%` lên `91.30%` rồi `100.0%`, khiến chỉ số **cost / câu trả lời đúng giảm hơn 11 lần** (`$0.00039675 → $0.00003469`). Điều này chứng tỏ đánh giá hiệu quả đầu tư của RAG phải nhìn vào **cost / câu đúng** chứ không phải cost / câu gọi.
- **Latency:** `v2` chịu thêm một lượng trễ nhỏ cho bước tìm kiếm tri thức (`MOCK_RETRIEVAL_MS ≈ 20ms`, `p50` tăng nhẹ từ `185.6 ms → 202.3 ms`), hoàn toàn xứng đáng để đổi lấy độ chính xác `100%`.

**Quality gate trong CI/CD (Exercise 7.3):**
- Khi chạy thử kiểm tra regression `python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json`, script phát hiện **20 câu bị regression**, in `Quality gate: ❌ FAIL` và trả về **exit code `1`**.
- Đã cấu hình sẵn workflow GitHub Actions tại [`.github/workflows/eval.yml`](.github/workflows/eval.yml): mỗi khi có Pull Request vào `main`, CI tự khởi động agent v2, chạy `eval/run_eval.py --min-accuracy 0.85 --baseline ../../../reports/eval_v2.json`. Nếu accuracy thấp hơn 85% hoặc bất kỳ câu nào đang đúng ở baseline bị sai đi (regression), lệnh trả exit code `1` làm **job CI fail** và tự động **chặn merge PR** (khi bật Branch Protection Rule yêu cầu status check `eval`).

---

## 4. Observability stack (production)

### 4.1 Screenshot & Quan sát Dashboard Grafana (Exercise 7.4)

- [x] Dashboard Grafana khi đang có tải (thấy rõ 4 Golden Signals, Latency p50/p95/p99, Requests/s theo status, Tokens/s, Cost burn rate) — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (`4f0e99c12fc09e0f8b84e560bc352459`, thấy rõ `chat mock-llm-small` chiếm `1.7s` / `98.6%`) — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (`c1154500bc96898189bd71111696c836`, có event `exception` và stacktrace `LLMError: 503`) — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **cả 4/4 alert đang cùng `FIRING`** (`AgentHighErrorRate`, `AgentHighLatencyP95`, `AgentInstanceDown`, `LLMCostBurnRateHigh`) — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời câu hỏi Exercise 7.4 (số liệu đo từ Prometheus/Grafana khi chạy tải trên 3 instances):**
1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Trong giai đoạn tải ổn định trên 3 instances: `avg = 231.84 ms`, `p95 = 293.42 ms` (khoảng cách ~62 ms), trong khi đường `p99` trên Grafana nằm ở vùng **`~1.7–1.8 s`** (cách xa `avg` hơn **7 lần**). Khoảng cách lớn giữa `avg` và `p95`/`p99` phản ánh rõ hiện tượng **tail latency**: đa số request rất nhanh (~200ms) nhưng ~3% request dính nhánh chậm của LLM (~1.7s) làm đuôi phân phối bị kéo dài mạnh.
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic cho các instance không?**
   - **Có.** Tại thời điểm đo tải với 3 instances, Prometheus ghi nhận lưu lượng trên `/ask` chia gần như đều nhau qua cơ chế round-robin + Docker DNS (`resolve`):
     - `172.20.0.7:8000`: **`15.22 req/s`**
     - `172.20.0.8:8000`: **`14.11 req/s`**
     - `172.20.0.9:8000`: **`14.41 req/s`**
3. **Vì sao input tokens/s lớn hơn output tokens/s?**
   - Trong cùng khoảng đo tải, **`input = 3,362.98 tokens/s`** cao gần gấp đôi **`output = 1,766.47 tokens/s`** (~1.9×). Nguyên nhân vì agent `v2` (RAG) ghép **`SYSTEM_PROMPT` + tài liệu context truy xuất từ Knowledge Base + câu hỏi của người dùng** thành đầu vào gửi lên LLM, nên số input token luôn lớn hơn nhiều so với câu trả lời ngắn gọn ở đầu ra.
4. **`curl http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`HTTP 404 Not Found`** (đã kiểm chứng trực tiếp). Trong `nginx/nginx.conf`, rule `location = /metrics { return 404; }` cố tình **chặn không public `/metrics` ra Internet**, vì endpoint metrics để lộ cấu trúc route, lưu lượng, chi phí và thông tin nội bộ hệ thống; chỉ Prometheus nằm trong cùng mạng Docker nội bộ `obs_net` mới được scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" (Exercise 7.6)

*(Unit test alert rules bằng `promtool test rules /p/alert_rules_test.yml` → **`SUCCESS`**).*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, đạt `19.73%–20.26% > 5%`) | **`94.1 giây`** (`pending` ở `+34.0s`) | Golden Signals → **Error rate** (đỏ) & **Requests/s theo status code** (`503` tăng vọt) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, đạt `1.95s > 1s`) | **`149.4 giây`** (`pending` ở `+34.0s`) | Golden Signals → **Latency p95** (đỏ) & **Latency /ask — p50 / p95 / p99** |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, đạt `$10.60–$11.39/giờ > $2/giờ`) | **`~174 giây`** (`pending` ở `+54.0s`) | LLM → **Cost burn rate (USD/giờ)** & **LLM latency p95 theo model** |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`for: 30s`, `up{instance="172.20.0.4:8000"} == 0`) | **`40.2 giây`** (`pending` ở `+10.1s`) | Golden Signals → **Instances up** giảm & **Requests/s theo instance** |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | LLM → **Retrieval hit ratio** mất dữ liệu, **Tokens/s** giảm mạnh & bảng **Phiên bản đang chạy** đổi sang `v1` |

**Phân tích thí nghiệm E & thí nghiệm D:**
- **Vì sao thí nghiệm E (`AGENT_VERSION=v1`) không làm alert nào firing và cách phát hiện trong production?**
  - Các alert hiện tại chỉ giám sát **tín hiệu hạ tầng** (HTTP 5xx, latency p95, container up/down, chi phí token). Khi đổi nhầm sang `v1`, hệ thống thậm chí còn nhanh hơn và rẻ hơn (không gọi retrieval, ít token hơn) nên mọi đèn hạ tầng đều xanh trong khi accuracy sụp đổ từ `100% → 4.35%`.
  - Để phát hiện lỗi suy giảm chất lượng trong production, cần kết hợp: (1) **CI/CD Quality Gate** chạy `eval/run_eval.py` trên golden dataset chặn ngay trước khi release, (2) **Online Evaluation** lấy mẫu định kỳ (vd 1–5% traffic thật) chấm điểm bằng **LLM-as-a-Judge** rồi đẩy metric `agent_eval_accuracy` sang Prometheus để cảnh báo, và (3) theo dõi **Retrieval Hit Ratio** (alert nếu tụt đột ngột) cùng phản hồi người dùng (thumbs up/down, tỷ lệ hỏi lại).
- **Ghi chú thêm về thí nghiệm D (lỗi 504 tại Nginx):** Khi `docker pause` làm container treo cứng, Nginx chờ quá `proxy_read_timeout` (10s) sẽ trả `504 Gateway Timeout` cho client nhưng **panel Error rate của agent không ghi nhận lỗi 504 này**, vì request chưa bao giờ được tiến trình agent xử lý xong để tăng counter `http_requests_total`. Do đó production cần giám sát thêm metrics ở tầng Load Balancer/Nginx và synthetic probing từ bên ngoài.

### 4.3 Debug bằng trace (Exercise 7.5)

**1. Trace chậm tiêu biểu (`screenshots/jaeger-slow-trace.png`):**
- `trace_id`: `4f0e99c12fc09e0f8b84e560bc352459`
- Tổng thời gian (`POST /ask`): **`1721.3 ms`** (`1.7s` trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** — **`1697.1 ms` (`98.6%` tổng thời gian)** *(trong khi bước `agent.retrieve_context` chỉ mất `21.9 ms` = `1.3%` — chứng tỏ nút thắt nằm ở upstream LLM, không phải ở code FastAPI hay retrieval)*.
- Dòng log JSON tương ứng (lấy từ `docker compose -p k5-day14-observability logs agent` theo `trace_id`):

```json
{"ts": "2026-11-25T09:25:32.011993+00:00", "level": "INFO", "service": "observable-agent", "instance": "001caa113cde", "event": "llm_call", "trace_id": "4f0e99c12fc09e0f8b84e560bc352459", "span_id": "5aab7e35f3771ffe", "request_id": "0a3fba82329a", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1697.1}
{"ts": "2026-11-25T09:25:32.012294+00:00", "level": "INFO", "service": "observable-agent", "instance": "001caa113cde", "event": "http_request", "trace_id": "4f0e99c12fc09e0f8b84e560bc352459", "span_id": "5aab7e35f3771ffe", "request_id": "0a3fba82329a", "method": "POST", "route": "/ask", "status": 200, "ms": 1721.3}
```

**2. Trace lỗi tiêu biểu (`screenshots/jaeger-error-trace.png`):**
- `trace_id`: `c1154500bc96898189bd71111696c836` (`POST /ask` trả `503`, tổng thời gian `90.8 ms`; span `chat mock-llm-small` dài `69.7 ms` mang trạng thái lỗi đỏ `!`, `error.type = upstream_unavailable` và event `exception` chứa `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`).
- Dòng log JSON tương ứng:

```json
{"ts": "2026-11-25T09:29:04.680130+00:00", "level": "INFO", "service": "observable-agent", "instance": "001caa113cde", "event": "llm_error", "trace_id": "c1154500bc96898189bd71111696c836", "span_id": "cf848a1abec4dcbc", "request_id": "12df01ef7581", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T09:29:04.680991+00:00", "level": "INFO", "service": "observable-agent", "instance": "001caa113cde", "event": "http_request", "trace_id": "c1154500bc96898189bd71111696c836", "span_id": "cf848a1abec4dcbc", "request_id": "12df01ef7581", "method": "POST", "route": "/ask", "status": 503, "ms": 90.8}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`)*

**Số liệu cho endpoint chính `POST /ask` (và `Aggregated` trong ngoặc):**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 (`scale_1_stats.csv`) | 59.50 *(Agg: 65.56)* | 200 *(Agg: 190)* | 300 *(Agg: 280)* | 1700 *(Agg: 1700)* | 57 / 7,112 — 0.80% *(Agg: 57 / 7,837 — 0.73%)* |
| 3 (`scale_3_stats.csv`) | 59.93 *(Agg: 65.90)* | 190 *(Agg: 190)* | 230 *(Agg: 230)* | 1700 *(Agg: 1700)* | 80 / 7,164 — 1.12% *(Agg: 80 / 7,878 — 1.02%)* |

**Giải thích kết quả:**
1. **Scale từ 1 lên 3 instances CÓ cải thiện rõ rệt `p95` và `max latency`:**
   - `p95` của `POST /ask` giảm từ **`300 ms` → `230 ms`** (giảm **23.3%**, `Aggregated` giảm `280 ms → 230 ms`), `p50` giảm từ `200 ms → 190 ms`, và độ trễ cực đại (`Max`) giảm từ `2,159 ms → 1,756 ms`. Lý do là mỗi container `agent` bị giới hạn `0.5 CPU`; khi chỉ có 1 instance gánh toàn bộ ~66 req/s kèm overhead OpenTelemetry/Prometheus sẽ xuất hiện tranh chấp CPU & hàng đợi nhẹ, còn khi chia đều tải sang 3 instances (~22 req/s mỗi máy) thì hiện tượng nghẽn CPU biến mất hoàn toàn.
2. **Vì sao RPS không tăng gấp 3 và `p99` vẫn giữ nguyên `1700 ms`? Nút thắt nằm ở đâu?**
   - **Về RPS (~65–66 req/s ở cả hai mức):** Nút thắt thông lượng ở bài đo này nằm ở **phía client tạo tải (Locust)**: mỗi trong 100 virtual users có `wait_time = between(0.5, 2)` (~1.25s nghỉ trung bình) cộng ~0.23s thời gian phản hồi ≈ `1.48s`/chu kỳ → tổng RPS tối đa về mặt toán học chỉ khoảng `100 / 1.48 ≈ 67 req/s`. Để thấy RPS tăng gấp 3 cần tăng số user lớn hơn nữa hoặc giảm `wait_time`.
   - **Về `p99 = 1700 ms` và tỷ lệ lỗi `~1%`:** Nút thắt ở đuôi phân phối nằm ở **upstream LLM** (`MOCK_SLOW_RATE=0.03` cộng thêm `1500ms` và `MOCK_ERROR_RATE=0.01` gây lỗi 503). Scale ngang tầng agent **không thể giảm latency hay lỗi của LLM provider bên ngoài** — muốn xử lý nút thắt này phải áp dụng semantic caching, streaming (giảm TTFT), retry có backoff/circuit breaker hoặc fallback sang model/provider dự phòng.

---

## 6. Kết luận

- **3 điều cốt lõi học được về Benchmark & Observability:**
  1. **Đo đúng chỉ số thay vì nhìn trung bình:** Latency trung bình che giấu tail latency (`p95`/`p99`), còn tổng chi phí mỗi lần gọi che giấu hiệu quả thật — với AI Agent, phải đo **SLO theo p95/p99** và so sánh phiên bản theo **cost / câu trả lời đúng** kèm **eval regression gate** trong CI.
  2. **Ba trụ cột Metrics – Traces – Logs chỉ thực sự mạnh khi liên kết chặt chẽ:** Metrics trên Grafana báo động *hệ thống đang chậm/lỗi*, Traces trên Jaeger chỉ đích danh *span `chat mock-llm-small` chiếm 98.6% thời gian*, và `trace_id` giúp tra ngay dòng JSON log chi tiết chỉ trong vài giây.
  3. **Hạ tầng khoẻ không đồng nghĩa AI trả lời đúng:** Thí nghiệm E (`AGENT_VERSION=v1`) chứng minh mọi metric hạ tầng và alert vẫn xanh dù độ chính xác tụt từ `100%` xuống `4.35%`; đồng thời cần kiểm soát cardinality của label metric và ẩn `/metrics` sau Reverse Proxy.
- **Nếu đưa agent này lên production thật, cần bổ sung thêm các metric & alert sau:**
  - **LLM & UX metrics:** `llm_ttft_seconds` (Time To First Token khi dùng streaming), `llm_tokens_per_second` (tốc độ sinh token), `agent_retrieval_hit_ratio` (cảnh báo khi tỷ lệ tìm thấy tài liệu tụt sâu), `agent_cache_hit_ratio` (hiệu quả Redis/semantic cache).
  - **Chất lượng & An toàn:** Online eval score (LLM-as-a-Judge) trên mẫu traffic thật, tỷ lệ prompt injection / guardrail bị kích hoạt, và tỷ lệ feedback tiêu cực từ người dùng.
  - **Tầng biên (Edge/Gateway) & Hạ tầng:** Metrics từ Nginx/API Gateway để bắt lỗi `429` (rate limit), `402` (vượt budget) và `504` (timeout phía LB mà agent không thấy), cộng thêm **Alertmanager** định tuyến cảnh báo theo mức độ (`warning` → Slack, `critical` → PagerDuty) kèm synthetic blackbox probe định kỳ từ bên ngoài.
