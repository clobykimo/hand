import logging
import os
import sys
import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from borax.calendars.lunardate import LunarDate
from google.cloud import firestore

# [輕量版] 移除自動化模組
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from playwright.async_api import async_playwright
# import smtplib
# from email.message import EmailMessage

# 設定 Log 格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

# ---------------- 設定區 ----------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"
# [輕量版] SMTP 設定暫時移除
# SMTP_CONFIG = { ... } 
SYSTEM_BASE_URL = "https://hand-316288530636.asia-east1.run.app"
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

app = FastAPI(title="達摩一掌經．生命藍圖導航系統 - V10.0 Lite 輕量競速版")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

db = None
try:
    db = firestore.Client()
    logger.info("✅ Firestore 連線成功")
except Exception as e:
    logger.warning(f"⚠️ Firestore 連線失敗: {e}")

# ---------------- 知識庫 (保留完整邏輯) ----------------
ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
STARS_INFO = {
    '子': {'name': '天貴星', 'element': '水'}, '丑': {'name': '天厄星', 'element': '土'},
    '寅': {'name': '天權星', 'element': '木'}, '卯': {'name': '天破星', 'element': '木'},
    '辰': {'name': '天奸星', 'element': '土'}, '巳': {'name': '天文星', 'element': '火'},
    '午': {'name': '天福星', 'element': '火'}, '未': {'name': '天驛星', 'element': '土'},
    '申': {'name': '天孤星', 'element': '金'}, '酉': {'name': '天刃星', 'element': '金'},
    '戌': {'name': '天藝星', 'element': '土'}, '亥': {'name': '天壽星', 'element': '水'}
}
ASPECTS_ORDER = ["總命運", "形象", "幸福", "事業", "變動", "健康", "愛情", "領導", "親信", "根基", "朋友", "錢財"]
STAR_MODIFIERS = {'天貴星': 30, '天福星': 30, '天文星': 30, '天壽星': 30, '天權星': 10, '天藝星': 10, '天驛星': 10, '天奸星': 10, '天孤星': -20, '天破星': -20, '天刃星': -20, '天厄星': -20}
RENHE_MODIFIERS = {'天貴星': 10, '天福星': 10, '天文星': 10, '天壽星': 10, '天權星': 5, '天藝星': 5, '天驛星': 5, '天奸星': 5, '天孤星': -10, '天破星': -10, '天刃星': -10, '天厄星': -10}
BAD_STARS = ['天厄星', '天破星', '天刃星']

# ---------------- 核心函數 (保留 V9.6 雙軌邏輯) ----------------
def get_zhi_index(zhi_char): return ZHI.index(zhi_char) if zhi_char in ZHI else 0
def get_next_position(start_index, steps, direction=1): return (start_index + (steps * direction)) % 12

def get_element_relation(me, target):
    PRODUCING = {'水': '木', '木': '火', '火': '土', '土': '金', '金': '水'}
    CONTROLING = {'水': '火', '火': '金', '金': '木', '木': '土', '土': '水'}
    if PRODUCING.get(target) == me: return {"type": "生我", "score": 80} 
    if me == target: return {"type": "比旺", "score": 75}
    if PRODUCING.get(me) == target: return {"type": "我生", "score": 60}  
    if CONTROLING.get(me) == target: return {"type": "我剋", "score": 35}  
    if CONTROLING.get(target) == me: return {"type": "剋我", "score": 20}
    return {"type": "未知", "score": 60}

def solar_to_one_palm_lunar(solar_date_str):
    if not solar_date_str: return None
    try:
        y, m, d = map(int, solar_date_str.split('-'))
        lunar = LunarDate.from_solar_date(y, m, d)
        year_zhi_idx = (lunar.year - 4) % 12
        final_month = lunar.month
        if lunar.leap and lunar.day > 15: final_month += 1
        return {"year_zhi": ZHI[year_zhi_idx], "month": final_month, "day": lunar.day, "lunar_year_num": lunar.year, "lunar_str": f"農曆 {lunar.year}年 {('閏' if lunar.leap else '')}{lunar.month}月 {lunar.day}日"}
    except: return None

def parse_target_date(mode, calendar_type, year, month, day, hour_zhi):
    try:
        target_lunar_year = year; target_lunar_month = month; target_lunar_day = day; display_info = ""
        dual_info = {"solar": "", "lunar": ""}
        
        if calendar_type == 'solar':
            lunar = LunarDate.from_solar_date(year, month, day)
            target_lunar_year = lunar.year; target_lunar_month = lunar.month; target_lunar_day = lunar.day
            leap_str = "閏" if lunar.leap else ""
            if lunar.leap and lunar.day > 15: 
                target_lunar_month += 1; leap_str = "閏(進)"
            
            dual_info["solar"] = f"{year}-{month}-{day}"
            dual_info["lunar"] = f"{lunar.year}年{leap_str}{lunar.month}月{lunar.day}日"
            display_info = f"國曆 {dual_info['solar']} (農曆 {dual_info['lunar']})"
        else:
            try:
                lunar_obj = LunarDate(year, month, day)
                solar_obj = lunar_obj.to_solar_date()
                dual_info["solar"] = f"{solar_obj.year}-{solar_obj.month}-{solar_obj.day}"
                dual_info["lunar"] = f"{year}年{month}月{day}日"
                display_info = f"農曆 {dual_info['lunar']} (國曆 {dual_info['solar']})"
            except:
                dual_info["lunar"] = f"{year}年{month}月{day}日"
                display_info = f"農曆 {year}年{month}月{day}日"

        return {
            "lunar_year": target_lunar_year, "lunar_month": target_lunar_month, "lunar_day": target_lunar_day,
            "year_zhi": ZHI[(target_lunar_year - 4) % 12], "hour_zhi": hour_zhi, "display_info": display_info,
            "dual_info": dual_info
        }
    except Exception as e:
        return {
            "lunar_year": year, "lunar_month": month, "lunar_day": day, 
            "year_zhi": ZHI[(year-4)%12], "hour_zhi": hour_zhi, 
            "display_info": f"日期錯誤", "dual_info": {"solar":"-", "lunar":"-"}
        }

class OnePalmSystem:
    def __init__(self, gender, birth_year_zhi, birth_month_num, birth_day_num, birth_hour_zhi):
        self.gender = gender; self.direction = 1 if gender == 1 else -1
        self.year_idx = get_zhi_index(birth_year_zhi)
        self.month_idx = get_next_position(self.year_idx, birth_month_num - 1, self.direction)
        self.day_idx = get_next_position(self.month_idx, birth_day_num - 1, self.direction)
        self.hour_idx = get_next_position(self.day_idx, get_zhi_index(birth_hour_zhi), self.direction)
    
    def get_base_chart(self):
        chart = {}; keys = [("年柱", self.year_idx), ("月柱", self.month_idx), ("日柱", self.day_idx), ("時柱", self.hour_idx)]
        for key, idx in keys: chart[key] = {**STARS_INFO[ZHI[idx]], "zhi": ZHI[idx], "name": STARS_INFO[ZHI[idx]]['name']}
        return chart

    def calculate_hierarchy(self, current_age, target_data, scope):
        start_luck = get_next_position(self.hour_idx, 1, self.direction)
        luck_stage = (current_age - 1) // 7 
        big_luck_idx = get_next_position(start_luck, luck_stage, self.direction)
        hierarchy = {"big_luck": {**STARS_INFO[ZHI[big_luck_idx]], "zhi": ZHI[big_luck_idx]}}
        
        t_year_zhi_idx = get_zhi_index(target_data['year_zhi'])
        flow_year_idx = get_next_position(big_luck_idx, t_year_zhi_idx, self.direction)
        hierarchy["year"] = {**STARS_INFO[ZHI[flow_year_idx]], "zhi": ZHI[flow_year_idx]}
        
        flow_month_idx = get_next_position(flow_year_idx, target_data['lunar_month'] - 1, self.direction)
        hierarchy["month"] = {**STARS_INFO[ZHI[flow_month_idx]], "zhi": ZHI[flow_month_idx]}
        
        flow_day_idx = get_next_position(flow_month_idx, target_data['lunar_day'] - 1, self.direction)
        hierarchy["day"] = {**STARS_INFO[ZHI[flow_day_idx]], "zhi": ZHI[flow_day_idx]}
        
        t_hour_idx = get_zhi_index(target_data['hour_zhi'])
        flow_hour_idx = get_next_position(flow_day_idx, t_hour_idx, self.direction)
        hierarchy["hour"] = {**STARS_INFO[ZHI[flow_hour_idx]], "zhi": ZHI[flow_hour_idx]}
        return hierarchy

    def calculate_full_trend(self, hierarchy, scope, lunar_data, target_data, system_obj):
        trend_response = { "axis_labels": [], "datasets": {}, "adjustments": {}, "renhe_scores": [], "tooltips": {}, "target_index": -1 }
        
        for name in ASPECTS_ORDER: 
            trend_response["datasets"][name] = []
            trend_response["adjustments"][name] = []
            trend_response["tooltips"][name] = [] 
        
        loop_items = []
        target_val_match = -1
        
        if scope == 'year':
            current_idx = get_zhi_index(hierarchy['year']['zhi'])
            base_year = target_data['lunar_year']
            for i in range(-6, 7):
                year_val = base_year + i
                y_zhi = ZHI[(year_val - 4) % 12]
                label = [f"{year_val}", f"({y_zhi}年)"]
                loop_items.append({'offset': i, 'label': label, 'type': 'year', 'val': year_val})
                if i == 0: target_val_match = len(loop_items) - 1

        elif scope == 'month':
            t_year = target_data['lunar_year']
            for i in range(1, 13):
                try:
                    l_date = LunarDate(t_year, i, 1)
                    s_date = l_date.to_solar_date()
                    s_label = f"{s_date.month}/{s_date.day}~"
                except: s_label = "推算中"
                label = [f"{i}月", f"{s_label}"]
                loop_items.append({'val': i, 'label': label, 'type': 'month'})
            target_val_match = target_data['lunar_month'] - 1

        elif scope == 'day':
            t_year = target_data['lunar_year']
            t_month = target_data['lunar_month']
            days_in_month = 30 
            try: 
                valid_month = max(1, min(12, t_month))
                days_in_month = LunarDate(t_year, valid_month, 1).days_in_month 
            except: pass
            
            for i in range(1, days_in_month + 1):
                try:
                    valid_month = max(1, min(12, t_month))
                    l_date = LunarDate(t_year, valid_month, i)
                    s_date = l_date.to_solar_date()
                    label = [f"{s_date.month}/{s_date.day}", f"(初{i})" if i < 11 else f"({i})"]
                except: label = [f"{i}日", ""]
                loop_items.append({'val': i, 'label': label, 'type': 'day'})
            target_val_match = target_data['lunar_day'] - 1

        elif scope == 'hour':
            for i, z in enumerate(ZHI):
                time_range = f"{((i-1)*2+24)%24:02}-{((i*2)+1)%24:02}"
                label = [f"{time_range}", f"({z}時)"]
                loop_items.append({'val': z, 'label': label, 'type': 'hour'})
            target_val_match = get_zhi_index(target_data['hour_zhi'])

        trend_response["target_index"] = target_val_match

        current_fy_idx = get_zhi_index(hierarchy['year']['zhi']) 
        current_fm_idx = get_zhi_index(hierarchy['month']['zhi'])
        current_fd_idx = get_zhi_index(hierarchy['day']['zhi'])   
        
        pillar_indices = [system_obj.year_idx, system_obj.month_idx, system_obj.day_idx, system_obj.hour_idx]
        
        for point in loop_items:
            trend_response["axis_labels"].append(point['label'])
            time_star_info = None
            
            if scope == 'year':
                dynamic_idx = get_next_position(current_fy_idx, point['offset'], system_obj.direction)
            elif scope == 'month':
                offset = point['val'] - 1
                dynamic_idx = get_next_position(current_fy_idx, offset, system_obj.direction)
            elif scope == 'day':
                offset = point['val'] - 1
                dynamic_idx = get_next_position(current_fm_idx, offset, system_obj.direction)
            elif scope == 'hour':
                h_idx = get_zhi_index(point['val']) if isinstance(point['val'], str) else point['val']
                dynamic_idx = get_next_position(current_fd_idx, h_idx, system_obj.direction)
            
            time_star_info = STARS_INFO[ZHI[dynamic_idx]]
            me_el = time_star_info['element'] 
            age_star_name = time_star_info['name']
            
            renhe_val = RENHE_MODIFIERS.get(age_star_name, 0)
            trend_response["renhe_scores"].append({"score": renhe_val, "star": age_star_name})

            for i, name in enumerate(ASPECTS_ORDER):
                curr_idx = (system_obj.hour_idx + i) % 12
                aspect_star_info = STARS_INFO[ZHI[curr_idx]]
                
                current_guest_el = aspect_star_info['element']
                current_guest_name = aspect_star_info['name']
                current_host_el = me_el
                current_host_name = age_star_name

                if name == "總命運":
                    upper_level_star = None
                    upper_level_label = ""
                    if scope == 'year': upper_level_star = hierarchy['big_luck']; upper_level_label = "(大運)"
                    elif scope == 'month': upper_level_star = hierarchy['year']; upper_level_label = "(流年)"
                    elif scope == 'day': upper_level_star = hierarchy['month']; upper_level_label = "(流月)"
                    elif scope == 'hour': upper_level_star = hierarchy['day']; upper_level_label = "(流日)"
                        
                    if upper_level_star:
                        current_host_el = upper_level_star['element']
                        current_host_name = upper_level_star['name'] + upper_level_label
                        current_guest_el = time_star_info['element']
                        current_guest_name = time_star_info['name'] + "(值星)"

                rel = get_element_relation(me=current_host_el, target=current_guest_el)
                trend_response["datasets"][name].append(rel["score"])
                grade_score = STAR_MODIFIERS.get(aspect_star_info['name'], 0)
                root_score = 10 if curr_idx in pillar_indices else 0
                trend_response["adjustments"][name].append(grade_score + root_score)
                date_str = point['label'][0] + point['label'][1]
                trend_response["tooltips"][name].append(f"[{date_str}] {current_guest_name} {rel['type']} {current_host_name}")
                
        return trend_response

    def check_risk(self, target_year):
        risks = []
        star = STARS_INFO[ZHI[self.hour_idx]]['name']
        if star in BAD_STARS: risks.append(f"命帶{star}")
        return risks

# ---------------- API 模型 ----------------
# [V10.0] AI 請求模型
class AIRequest(BaseModel):
    message: str  
    history: List[Dict[str, str]] = []  
    context_data: Optional[Dict[str, Any]] = {} 

class UserRequest(BaseModel):
    gender: int; solar_date: str; hour: str; target_calendar: str = 'lunar'; target_scope: str = 'year'; target_year: int; target_month: int = 1; target_day: int = 1; target_hour: str = '子'
class SaveRequest(BaseModel):
    solar_date: Optional[str] = None; gender: Optional[int] = None; hour: Optional[str] = None; target_year: Optional[int] = None
    client_name: Optional[str] = None; email: Optional[str] = None; phone: Optional[str] = ""; tags: Optional[List[str]] = []
    note: Optional[str] = ""; ai_log: Optional[Dict[str, Any]] = {}
    image_urls: Optional[List[str]] = []; audio_url: Optional[str] = ""; transcript: Optional[str] = ""
    relations: Optional[List[Dict[str, Any]]] = []; consent_signed: Optional[bool] = False; consent_date: Optional[str] = ""

# ---------------- API 路由 ----------------
@app.get("/", response_class=HTMLResponse)
async def read_root(): return open("index.html", "r", encoding="utf-8").read() if os.path.exists("index.html") else "<h1>Error</h1>"
@app.get("/crm", response_class=HTMLResponse)
async def read_crm(): return open("crm.html", "r", encoding="utf-8").read() if os.path.exists("crm.html") else "<h1>Error</h1>"
@app.get("/consent_page", response_class=HTMLResponse)
async def read_consent_page(): return open("consent.html", "r", encoding="utf-8").read() if os.path.exists("consent.html") else "<h1>Error</h1>"

@app.post("/api/transcribe_audio")
async def transcribe_audio(file: UploadFile = File(...)):
    if not OPENAI_API_KEY or "請在此" in OPENAI_API_KEY: return {"text": "API Key Error", "path": ""}
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, safe_filename)
        with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as audio_file: transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return {"text": transcript.text, "path": f"/uploads/{safe_filename}"}
    except Exception as e: return {"text": str(e), "path": ""}

@app.post("/api/calculate")
async def calculate(req: UserRequest):
    try:
        lunar_data = solar_to_one_palm_lunar(req.solar_date)
        if not lunar_data: raise ValueError("出生日期解析失敗")
        
        target_data = parse_target_date(req.target_scope, req.target_calendar, req.target_year, req.target_month, req.target_day, req.target_hour)
        
        age = target_data['lunar_year'] - lunar_data['lunar_year_num'] + 1
        system = OnePalmSystem(req.gender, lunar_data['year_zhi'], lunar_data['month'], lunar_data['day'], req.hour)
        base_chart = system.get_base_chart()
        hierarchy = system.calculate_hierarchy(age, target_data, req.target_scope)
        aspects = []
        base_idx = get_zhi_index(hierarchy['year']['zhi']) if req.target_scope == 'year' else get_zhi_index(hierarchy['year']['zhi'])
        
        host_star = hierarchy['year'] 
        if req.target_scope == 'month': host_star = hierarchy['month']
        elif req.target_scope == 'day': host_star = hierarchy['day']
        elif req.target_scope == 'hour': host_star = hierarchy['hour']
        
        for i, name in enumerate(ASPECTS_ORDER):
            curr_idx = (base_idx + i) % 12 
            guest_star_info = STARS_INFO[ZHI[curr_idx]] 
            current_host_el = host_star['element']
            if name == "總命運":
                if req.target_scope == 'year': current_host_el = hierarchy['big_luck']['element']
                elif req.target_scope == 'month': current_host_el = hierarchy['year']['element']
                elif req.target_scope == 'day': current_host_el = hierarchy['month']['element']
                elif req.target_scope == 'hour': current_host_el = hierarchy['day']['element']
            rel = get_element_relation(me=current_host_el, target=guest_star_info['element'])
            aspects.append({ "name": name, "star": guest_star_info['name'], "element": guest_star_info['element'], "zhi": ZHI[curr_idx], "relation": rel['type'], "is_alert": (rel['type'] in ['我剋','剋我']) })
        
        trend_data = system.calculate_full_trend(hierarchy, req.target_scope, lunar_data, target_data, system)
        
        return {"lunar_info": lunar_data['lunar_str'], "age": age, "base_chart": base_chart, "hierarchy": hierarchy, "target_display": target_data['display_info'], "dual_info": target_data.get('dual_info', {}), "aspects": aspects, "ai_prompt": "", "trend_data": trend_data}
    except Exception as e: 
        logger.error(f"Calculate Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/scan_family_risks")
async def scan_family_risks(req: SaveRequest):
    alerts = []
    target_year = req.target_year or 2026
    if not req.relations: return {"alerts": []}
    for p in req.relations:
        try:
            if not p.get('solar_date'): continue
            lunar = solar_to_one_palm_lunar(p['solar_date'])
            if not lunar: continue
            sys = OnePalmSystem(int(p.get('gender', 1)), lunar['year_zhi'], lunar['month'], lunar['day'], p.get('hour', '子'))
            risks = sys.check_risk(target_year)
            if risks: alerts.append({"name": p['name'], "relation": p['relation'], "risk": ", ".join(risks)})
        except: continue
    return {"alerts": alerts}

@app.post("/api/save_record")
async def save_record(req: SaveRequest):
    if not db: return {"status": "error"}
    doc_ref = db.collection('consultations').document()
    data = req.dict(); data['created_at'] = firestore.SERVER_TIMESTAMP
    doc_ref.set(data)
    return {"status": "success", "id": doc_ref.id}

@app.post("/api/update_record/{doc_id}")
async def update_record(doc_id: str, req: SaveRequest):
    if not db: return {"status": "error"}
    db.collection('consultations').document(doc_id).set(req.dict(exclude_unset=True), merge=True)
    return {"status": "success"}

@app.post("/api/sign_consent/{doc_id}")
async def sign_consent(doc_id: str):
    if not db: return {"status": "error"}
    db.collection('consultations').document(doc_id).update({"consent_signed": True, "consent_date": datetime.datetime.now().strftime("%Y-%m-%d")})
    return {"status": "success"}

@app.get("/api/search_records")
async def search_records(keyword: str = ""):
    if not db: return []
    try:
        docs = db.collection('consultations').order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        results = []
        for doc in docs:
            data = doc.to_dict(); data['id'] = doc.id
            if data.get('created_at'): data['created_at'] = datetime.datetime.fromtimestamp(data['created_at'].timestamp()).strftime("%Y-%m-%d")
            if keyword:
                search_target = f"{data.get('client_name','')} {data.get('note','')} {data.get('phone','')}"
                if keyword.lower() in search_target.lower(): results.append(data)
            else: results.append(data)
        return results
    except: return []

@app.delete("/api/delete_record/{doc_id}")
async def delete_record(doc_id: str):
    if not db: return {"status": "error"}
    db.collection('consultations').document(doc_id).delete()
    return {"status": "success"}

# [V10.0] AI 大腦核心：注入達摩邏輯與商業導購
@app.post("/api/ask_ai")
async def ask_ai(req: AIRequest):
    if "請在此" in OPENAI_API_KEY: return {"error": "API Key 未設定"}
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        # 1. 建構「系統人設」 (System Prompt) - 這是 AI 的靈魂
        ctx = req.context_data
        system_prompt = f"""
        你現在是「達摩一掌經」的專業戰略顧問，輔助「徐峰老師」進行命理諮詢。
        
        【你的核心邏輯】：
        1. 依據分數判斷吉凶 (底層邏輯)：
           - 80分 (生我)：大吉，貴人相助，輕鬆得利。
           - 75分 (比旺)：中吉，同伴合作，順水推舟。
           - 60分 (我生)：平運，才華展現，但需付出努力。
           - 35分 (我剋)：勞碌，雖然有掌控權，但過程辛苦，需親力親為。
           - 20分 (剋我)：凶險，壓力極大，受制於人，易有災禍。
        2. 說話風格：專業、理性、帶有戰略高度，不要過於迷信，用現代管理學術語解釋命理。
        3. 【商業導購指令】：若你發現某個重要宮位 (如總命運、事業、錢財) 分數低於 40 分 (35或20)，請務必在分析結尾加上：「⚠ 偵測到此處能量波動較大，建議預約徐峰老師進行一對一深度佈局，以化解風險。」

        【當前案主數據】：
        - 年齡：{ctx.get('age', '未知')}
        - 目標時間：{ctx.get('target_display', '未知')}
        - 命盤重點數據：{str(ctx.get('aspects', []))}
        """

        # 2. 組合對話歷史
        messages = [{"role": "system", "content": system_prompt}]
        recent_history = req.history[-6:] 
        messages.extend(recent_history)
        messages.append({"role": "user", "content": req.message})

        # 3. 發送請求
        res = client.chat.completions.create(
            model="gpt-4o", 
            messages=messages,
            temperature=0.7 
        )
        
        return {"reply": res.choices[0].message.content}

    except Exception as e:
        logger.error(f"AI Error: {str(e)}")
        return {"reply": f"AI 思考過載中，請稍後再試。({str(e)})"}

# [輕量版] 自動化排程暫時移除 (若日後需要可再開啟)
# scheduler = AsyncIOScheduler()
# @app.on_event("startup")
# async def start_scheduler_event(): ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
