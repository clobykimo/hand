# 使用官方 Python 輕量版映像檔
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# 複製需求檔並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼到容器內
COPY . .

# 設定環境變數 (確保 Python 輸出即時顯示)
ENV PYTHONUNBUFFERED=1

# 啟動指令 (Cloud Run 預設 Port 為 8080)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]