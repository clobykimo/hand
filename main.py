import logging
import os
import sys
import datetime
import shutil
import json
import uuid
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from borax.calendars.lunardate import LunarDate
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

app = FastAPI(title="達摩一掌經命理戰略中台 - V7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

db = None
try:
    db = firestore.Client()
    logger.info("✅ Firestore 連線成功")
except Exception as e:
    logger.warning(f"⚠️ Firestore 連線失敗: {e}")

# ---------------- 知識庫 & 核心算法 (保持不變) ----------------
ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
STARS_INFO = {
    '子': {'name': '天貴星', 'element': '水'}, '丑': {'name': '天厄星', 'element': '土'},
    '寅': {'name': '天權星', 'element': '木'}, '卯': {'name': '天破星', 'element': '木'},
    '辰': {'name': '天奸星', 'element': '土'}, '巳': {'name': '天文星', 'element': '火'},
    '午': {'name': '天福星', 'element': '火'}, '未': {'name': '天驛星', 'element': '土'},
    '申': {'name': '天孤星', 'element': '金'}, '酉': {'name': '天刃星', 'element': '金'},
    '戌': {'name': '天藝星', 'element': '土'}, '亥': {'name': '天壽星', 'element': '水'}
}
# 定義凶星與關鍵字 (用於自動預警)
BAD_STARS = ['天厄星', '天破星', '天刃星']
RISK_PALACES = ['命宮', '疾厄宮', '福德宮'] # 這裡簡化，實務上可根據需求調整

def get_zhi_index(zhi_char): return ZHI.index(zhi_char) if zhi_char in ZHI else 0
def get_next_position(start_index, steps, direction=1): return (start_index + (steps * direction)) % 12
def solar_to_one_palm_lunar(solar_date_str):
    try:
        y, m, d = map(int, solar_date_str.split('-'))
        lunar = LunarDate.from_solar_date(y, m, d)
        year_zhi_idx = (lunar.year - 4) % 12
        final_month = lunar.month
        if lunar.leap and lunar.day > 15: final_month += 1
        return {"year_zhi": ZHI[year_zhi_idx], "month": final_month, "day": lunar.day, "lunar_year_num": lunar.year}
    except: return None

class OnePalmSystem:
    def __init__(self, gender, birth_year_zhi, birth_month_num, birth_day_num, birth_hour_zhi):
        self.gender = gender; self.direction = 1 if gender == 1 else -1
        self.year_idx = get_zhi_index(birth_year_zhi)
        self.month_idx = get_next_position(self.year_idx, birth_month_num - 1, self.direction)
        self.day_idx = get_next_position(self.month_idx, birth_day_num - 1, self.direction)
        self.hour_idx = get_next_position(self.day_idx, get_zhi_index(birth_hour_zhi), self.direction)
    
    # 專門用於家庭風險掃描的輕量級計算
    def check_risk(self, current_lunar_year):
        # 簡單計算流年落點
        # 注意：這裡使用簡化的流年推算邏輯 (大運+流年)
        # 為了效能，這裡只示範「流年宮位」本身的星宿風險
        # 實務上需完整算出大運流年
        # 假設：流年只看年支對應的宮位 (簡化版)
        
        # 真正的流年計算需依賴年齡，這裡做一個快速估算
        # 暫時以 "年柱" 為基準跑流年 (僅作範例)
        risks = []
        
        # 檢查命宮 (時柱)
        star = STARS_INFO[ZHI[self.hour_idx]]['name']
        if star in BAD_STARS:
            risks.append(f"命帶{star}")
            
        return risks

# ---------------- API 模型 ----------------
class SaveRequest(BaseModel):
    solar_date: str; gender: int; hour: str; target_year: int; client_name: str; phone: str = ""; tags: List[str] = []; note: str = ""; ai_log: Dict[str, Any] = {}
    image_urls: List[str] = []; audio_url: str = ""; transcript: str = ""
    relations: List[Dict[str, Any]] = [] # [{'name':'xxx', 'relation':'父', 'solar_date':'...', 'hour':'子', 'gender':1}]
    consent_signed: bool = False; consent_date: str = ""

# ---------------- 核心 API ----------------

@app.get("/", response_class=HTMLResponse)
async def read_root():
    if os.path.exists("index.html"): return open("index.html", "r", encoding="utf-8").read()
    return "<h1>系統啟動中</h1>"

@app.get("/crm", response_class=HTMLResponse)
async def read_crm():
    if os.path.exists("crm.html"): return open("crm.html", "r", encoding="utf-8").read()
    return "<h1>CRM 頁面建置中</h1>"

# [V7.0] 數位同意書頁面
@app.get("/consent_page", response_class=HTMLResponse)
async def read_consent_page():
    if os.path.exists("consent.html"): return open("consent.html", "r", encoding="utf-8").read()
    return "<h1>同意書載入錯誤</h1>"

# [V7.0] 家族風險掃描 (Ecosystem Core)
@app.post("/api/scan_family_risks")
async def scan_family_risks(req: SaveRequest):
    alerts = []
    target_year = req.target_year or 2026
    
    # 遍歷關係人
    for p in req.relations:
        try:
            if not p.get('solar_date'): continue
            lunar = solar_to_one_palm_lunar(p['solar_date'])
            if not lunar: continue
            
            # 排盤
            sys = OnePalmSystem(int(p['gender']), lunar['year_zhi'], lunar['month'], lunar['day'], p['hour'])
            
            # 檢查風險 (這裡用簡單邏輯：如果命宮是凶星)
            # 進階版應計算流年
            risks = sys.check_risk(target_year)
            
            if risks:
                alerts.append({
                    "name": p['name'],
                    "relation": p['relation'],
                    "risk": ", ".join(risks),
                    "advice": "建議安排詳細流年諮詢"
                })
        except Exception as e:
            logger.error(f"Scan error for {p.get('name')}: {e}")
            continue
            
    return {"alerts": alerts}

# [V7.0] 簽署同意書 API
@app.post("/api/sign_consent/{doc_id}")
async def sign_consent(doc_id: str):
    if not db: return {"status": "error"}
    try:
        db.collection('consultations').document(doc_id).update({
            "consent_signed": True,
            "consent_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return {"status": "success"}
    except Exception as e: return {"status": "error", "msg": str(e)}

# ---------------- 原有功能 (保持不變) ----------------
# (transcribe_audio, calculate, ask_ai, save_record, search_records, delete_record...)
# 為節省篇幅，請保留您 V6.2 中的所有其他 API 函數
# 務必包含 transcribe_audio, calculate 等

@app.post("/api/transcribe_audio")
async def transcribe_audio(file: UploadFile = File(...)):
    if not OPENAI_API_KEY or "請在此填入" in OPENAI_API_KEY: return {"text": "⚠️ API Key 未設定", "path": ""}
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, safe_filename)
        with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as audio_file: transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return {"text": transcript.text, "path": f"/uploads/{safe_filename}"}
    except Exception as e: return {"text": f"Error: {str(e)}", "path": ""}

# ... (請保留 calculate, ask_ai, save_record, search_records, delete_record) ...
# 注意：save_record 需確保能存 relations 與 consent 欄位 (Pydantic 模型已更新，直接用即可)

@app.post("/api/save_record")
async def save_record(req: SaveRequest):
    if not db: return {"status": "error", "message": "資料庫未連接"}
    try:
        doc_ref = db.collection('consultations').document()
        data = req.dict(); data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(data)
        return {"status": "success", "id": doc_ref.id}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/calculate") # 簡化版佔位，請使用 V6.2 的完整 calculate
async def calculate(req: UserRequest):
    # 請將 V6.2 的 calculate 函數完整貼於此
    return {"status": "請貼上完整 calculate"} # 佔位符

@app.get("/api/search_records") # 簡化版佔位
async def search_records(keyword: str = ""):
    if not db: return []
    try:
        docs = db.collection('consultations').order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        results = []
        for doc in docs:
            data = doc.to_dict(); data['id'] = doc.id
            if data.get('created_at'): data['created_at'] = str(data['created_at']) # 簡化
            if keyword:
                if keyword.lower() in str(data).lower(): results.append(data)
            else: results.append(data)
        return results
    except: return []

@app.delete("/api/delete_record/{doc_id}")
async def delete_record(doc_id: str):
    if not db: return {"status": "error"}
    db.collection('consultations').document(doc_id).delete()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
