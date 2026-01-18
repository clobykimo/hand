# 使用輕量級 Python 基礎映像
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# 關鍵戰略：先複製 requirements.txt 並安裝依賴
# 這樣只要 requirements.txt 沒變，Docker 就會直接用快取，跳過安裝步驟！
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 最後才複製程式碼 (index.html, main.py)
# 因為這些變動最頻繁，放在最後一層，才不會破壞前面的快取
COPY . .

# 啟動命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
