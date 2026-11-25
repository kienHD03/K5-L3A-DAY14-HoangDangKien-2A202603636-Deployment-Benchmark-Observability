# Deployment Information

## Public URL
https://k5-l3a-day14-hoangdangkien-2a202603636-deploymen-production.up.railway.app

## Platform
Railway (Docker builder từ `06-lab-complete/Dockerfile` + Railway Redis service)

## Test Commands (CP6 Verification)

Đặt biến môi trường trước khi kiểm tra (không hardcode key vào file):

```bash
export BASE="https://k5-l3a-day14-hoangdangkien-2a202603636-deploymen-production.up.railway.app"
export AGENT_API_KEY="<your-secret-api-key>"
```

### 1. Liveness Probe (`GET /health` → `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200
```

### 2. Readiness Probe (`GET /ready` → `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200
```

### 3. Authentication Check — Missing API Key (`POST /ask` → `401`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Expected: 401
```

### 4. Authenticated Agent Call (`POST /ask` → `200`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"user_id":"test","question":"Hello"}'
# Expected: 200
```

### 5. Automated Grading Verification with Public URL
```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set on Platform
- `PORT` (Railway/Render tự động cấp phát và inject vào container)
- `ENVIRONMENT` (`production`)
- `AGENT_API_KEY` (Secret đặt trên Dashboard/CLI, không commit vào Git)
- `REDIS_URL` (Trỏ tới internal connection URL của Redis service trên nền tảng)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)
- `LOG_LEVEL` (`INFO`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
