# AI Guru #53 — API chat với model thật

Ứng dụng FastAPI chuyển `message` qua API model độc lập, trả `answer`. Có thể dùng OpenRouter hoặc server tương thích Chat Completions như vLLM. Không có chế độ echo hoặc fallback giả. Mỗi request là một lượt riêng, không lưu lịch sử.

## Chạy trên Linux/bash

Đã kiểm chứng với Python 3.12.9. Trong thư mục chứa `main.py`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip check
cp .env.example .env
```

Sửa `.env`: thay `LLM_MODEL` và `LLM_API_KEY` bằng cấu hình hợp lệ. Không để placeholder `REPLACE_...`. Cloud dùng `LLM_BASE_URL=https://openrouter.ai/api/v1`. Self-host ví dụ `http://127.0.0.1:18080/v1`, model ID đã phục vụ và key nếu server yêu cầu. Base URL không bao gồm `/chat/completions`. Không đưa key thật vào Git.

Biến môi trường tiến trình ghi đè file `.env` cạnh `config.py`. Để dùng file, có thể xóa các biến cũ trong shell hiện tại:

```bash
unset LLM_BASE_URL LLM_MODEL LLM_API_KEY LLM_TIMEOUT_SECONDS
ss -ltn '( sport = :18053 )'
python -m uvicorn main:app --host 127.0.0.1 --port 18053 --reload
```

Giữ terminal mở. Đổi cổng nếu có tiến trình khác đang nghe; sửa đồng bộ URL ứng dụng. Dùng 18053 thay cho 8000 để tránh trùng cổng mặc định thường dùng bởi Uvicorn/vLLM. Ví dụ model self-host dùng 18080; hai dịch vụ có cổng riêng. Sửa `.env` xong cần khởi động lại server.

Mở terminal thứ hai:

```bash
curl -i http://127.0.0.1:18053/health
curl -i --max-time 90 http://127.0.0.1:18053/chat \
  -H 'Content-Type: application/json' \
  --data '{"message":"Giải thích API bằng một câu tiếng Việt ngắn gọn."}'
curl -i http://127.0.0.1:18053/chat \
  -H 'Content-Type: application/json' --data '{"message":"   "}'
```

Health trả 200 và `{"status":"ok"}`. Chat hợp lệ trả 200 và `{"answer":"..."}` chứa text của model; văn bản thay đổi giữa các lần gọi. Chuỗi trắng trả 422 và không gọi model. Ctrl+C để dừng server.

Swagger: <http://127.0.0.1:18053/docs> → POST /chat → Try it out → nhập JSON → Execute. Schema gốc: <http://127.0.0.1:18053/openapi.json>.

## Hợp đồng và lỗi

- `message` bắt buộc, chuỗi strict, strip hai đầu rồi kiểm tra 1–2000 ký tự Python; từ chối field dư.
- `/health` chỉ kiểm tra liveness ứng dụng, không gọi model.
- 422: input không hợp lệ; `detail` là danh sách lỗi validation.
- 502: backend từ chối request hoặc không trả text đúng cấu trúc.
- 503: lỗi mạng, backend 429 hoặc 5xx.
- 504: timeout HTTP client.
- Lỗi backend có `detail.code` và `detail.message`; không chuyển nguyên lỗi provider ra client.
- `LLM_TIMEOUT_SECONDS` mặc định 60, áp dụng cho từng pha HTTPX, không phải tổng deadline.
- Startup kiểm tra URL/model/key/timeout; không kiểm tra key có được provider chấp nhận hay không.
- Backend khác OpenRouter có thể cần key; người vận hành phải cấu hình theo dịch vụ. Self-host không xác thực thì bỏ trống key.

## Kiểm thử

```bash
python -m pytest -q
```

Test dùng MockTransport để kiểm tra hợp đồng và lỗi, không tốn lượt model. Bản bài viết đi kèm có minh chứng chạy OpenRouter thật qua curl và Swagger; vLLM mới có hướng dẫn cấu hình, chưa được chạy live. Bộ khóa dependency có cảnh báo deprecation từ Starlette TestClient về HTTPX; kiểm thử vẫn đạt, cảnh báo được giữ trong bằng chứng.

`requirements-lock.txt` chứa cả runtime và test đã kiểm chứng; `requirements.txt` là dependency runtime trực tiếp, `requirements-dev.txt` thêm pytest. Không đưa vLLM vào môi trường API ứng dụng. Muốn dùng self-host cần chuẩn bị server model riêng.
