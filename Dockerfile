# 1. 使用官方 Python 基礎映像檔 (建議用 3.9 或 3.10)
FROM python:3.10-slim

# 2. 設定工作目錄
WORKDIR /app

# 3. 複製 requirements.txt 並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ======================================================
# 4. [GCP 專用] 安裝 Playwright 瀏覽器與系統相依套件
# 這是最關鍵的一步，相當於 Render 的 Build Command
# ======================================================
RUN playwright install chromium
RUN playwright install-deps

# 5. 複製所有程式碼到容器內
COPY . .

# 6. 設定環境變數 (讓 Python 知道即時輸出 Log)
ENV PYTHONUNBUFFERED=1

# 7. 啟動服務 (GCP Cloud Run 預設 Port 為 8080)
# 注意：這裡必須用 0.0.0.0 和 port 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
