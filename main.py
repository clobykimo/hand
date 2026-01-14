import logging
import os
import sys
import datetime
import shutil
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from borax.calendars.lunardate import LunarDate
from google.cloud import firestore

# 設定 Log 格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

# API Key 設定
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

app = FastAPI(title="達摩一掌經命理戰略中台 - V9.0 最終定案版")

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

# ---------------- 知識庫 ----------------
ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
STARS_INFO = {
    '子': {'name': '天貴星', 'element': '水'}, '丑': {'name': '天厄星', 'element': '土'},
    '寅': {'name': '天權星', 'element': '木'}, '卯': {'name': '天破星', 'element': '木'},
    '辰': {'name': '天奸星', 'element': '土'}, '巳': {'name': '天文星', 'element': '火'},
    '午': {'name': '天福星', 'element': '火'}, '未': {'name': '天驛星', 'element': '土'},
    '申': {'name': '天孤星', 'element': '金'}, '酉': {'name': '天刃星', 'element': '金'},
    '戌': {'name': '天藝星', 'element': '土'}, '亥': {'name': '天壽星', 'element': '水'}
}
ASPECTS_ORDER = ["總命運", "形象", "幸福", "事業", "變動", "健慾", "愛情", "領導", "親信", "根基", "朋友", "錢財"]

# [Level 2] 十二宮三品格
STAR_MODIFIERS = {
    '天貴星': 30, '天福星': 30, '天文星': 30, '天壽星': 30,
    '天權星': 10, '天藝星': 10, '天驛星': 10, '天奸星': 10,
    '天孤星': -20, '天破星': -20, '天刃星': -20, '天厄星': -20
}

# [Level 3] 根基人和 (歲數星加權)
RENHE_MODIFIERS = {
    '天貴星': 10, '天福星': 10, '天文星': 10, '天壽星': 10,
    '天權星': 5, '天藝星': 5, '天驛星': 5, '天奸星': 5,
    '天孤星': -10, '天破星': -10, '天刃星': -10, '天厄星': -10
}

BAD_STARS = ['天厄星', '天破星', '天刃星']

# ---------------- 核心函數 ----------------
def get_zhi_index(zhi_char): return ZHI.index(zhi_char) if zhi_char in ZHI else 0
def get_next_position(start_index, steps, direction=1): return (start_index + (steps * direction)) % 12

# [V9.1] 五行生剋分數 (修正：我生上調至 60)
def get_element_relation(me, target):
    # me = 主 (流年/大運), target = 客 (宮位/流年)
    PRODUCING = {'水': '木', '木': '火', '火': '土', '土': '金', '金': '水'}
    CONTROLING = {'水': '火', '火': '金', '金': '木', '木': '土', '土': '水'}
    
    # 1. 生我 (客生主)：大吉 80
    if PRODUCING.get(target) == me: return {"type": "生我", "score": 80} 
    
    # 2. 比旺 (客同主)：強吉 75
    if me == target: return {"type": "比旺", "score": 75}
    
    # 3. 我生 (主生客)：平吉 60 (原 50)
    # 說明：雖洩氣但為才華展現，視為及格。
    if PRODUCING.get(me) == target: return {"type": "我生", "score": 60}  
    
    # 4. 我剋 (主剋客)：勞碌 35
    if CONTROLING.get(me) == target: return {"type": "我剋", "score": 35}  
    
    # 5. 剋我 (客剋主)：凶險 20
    if CONTROLING.get(target) == me: return {"type": "剋我", "score": 20}
        
    return {"type": "未知", "score": 60}

def solar_to_one_palm_lunar(solar_date_str):
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
        if calendar_type == 'solar':
            lunar = LunarDate.from_solar_date(year, month, day)
            target_lunar_year = lunar.year; target_lunar_month = lunar.month; target_lunar_day = lunar.day
            display_info = f"國曆 {year}-{month}-{day} (農曆 {lunar.year}年{lunar.month}月{lunar.day}日)"
        else:
            lunar_obj = LunarDate(year, month, day)
            solar_obj = lunar_obj.to_solar_date()
            target_lunar_year = year; target_lunar_month = month; target_lunar_day = day
            display_info = f"農曆 {year}年{month}月{day}日 (國曆 {solar_obj.year}-{solar_obj.month}-{solar_obj.day})"
        return {"lunar_year": target_lunar_year, "lunar_month": target_lunar_month, "lunar_day": target_lunar_day, "year_zhi": ZHI[(target_lunar_year - 4) % 12], "hour_zhi": hour_zhi, "display_info": display_info}
    except: return {"lunar_year": year, "lunar_month": month, "lunar_day": day, "year_zhi": ZHI[(year-4)%12], "hour_zhi": hour_zhi, "display_info": f"日期錯誤"}

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
        
        # [V9.0] 鎖定：7年一運 (祖制)
        # 1-7歲=0, 8-14歲=1, 15-21歲=2 ...
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

    # [V9.0] 趨勢運算 (含特案：流年總命運 改對照 大運)
    def calculate_full_trend(self, hierarchy, scope, lunar_data, target_data, system_obj):
        trend_response = { "axis_labels": [], "datasets": {}, "adjustments": {}, "renhe_scores": [], "tooltips": {} }
        for name in ASPECTS_ORDER: 
            trend_response["datasets"][name] = []; trend_response["adjustments"][name] = []; trend_response["tooltips"][name] = []
        
        loop_range = []
        if scope == 'year':
            for y in range(target_data['lunar_year'] - 6, target_data['lunar_year'] + 7):
                try: l_date = LunarDate(y, 1, 1); s_date = l_date.to_solar_date(); label = [f"{y}", f"國{s_date.month}/{s_date.day}起"]
                except: label = [f"{y}", ""]
                loop_range.append({'type': 'year', 'val': y, 'label': label})
        else: 
            for i in range(1, 13):
                try: l_date = LunarDate(target_data['lunar_year'], i, 1); s_date = l_date.to_solar_date(); label = [f"{i}月", f"{s_date.month}/{s_date.day}"]
                except: label = [f"{i}月", ""]
                loop_range.append({'type': 'month', 'val': i, 'label': label})
        
        current_fy_idx = get_zhi_index(hierarchy['year']['zhi'])
        pillar_indices = [system_obj.year_idx, system_obj.month_idx, system_obj.day_idx, system_obj.hour_idx]
        
        for point in loop_range:
            trend_response["axis_labels"].append(point['label'])
            
            # 計算該時間點的流年星/流月星 (Time Star)
            if scope == 'year':
                offset = point['val'] - target_data['lunar_year']
                dynamic_fy_idx = get_next_position(current_fy_idx, offset, system_obj.direction)
                time_star_info = STARS_INFO[ZHI[dynamic_fy_idx]]
            else: 
                offset = point['val'] - 1 
                fm_idx = get_next_position(current_fy_idx, offset, system_obj.direction)
                time_star_info = STARS_INFO[ZHI[fm_idx]]
            
            # 標準邏輯：主 (Me) = 流年總命運
            me_el = time_star_info['element'] 
            age_star_name = time_star_info['name']
            
            renhe_val = RENHE_MODIFIERS.get(age_star_name, 0)
            trend_response["renhe_scores"].append({"score": renhe_val, "star": age_star_name})

            for i, name in enumerate(ASPECTS_ORDER):
                curr_idx = (system_obj.hour_idx + i) % 12
                aspect_star_info = STARS_INFO[ZHI[curr_idx]]
                
                # 客 (Target) = 宮位/事件
                current_guest_el = aspect_star_info['element']
                current_guest_name = aspect_star_info['name']
                
                # 主 (Host) = 流年
                current_host_el = me_el
                current_host_name = age_star_name

                # [特案 V9.0] 總命運特判
                # 若是「流年模式」且項目是「總命運」
                # 定義：主=大運, 客=流年
                if scope == 'year' and name == "總命運":
                    current_host_el = hierarchy['big_luck']['element']
                    current_host_name = hierarchy['big_luck']['name'] + "(大運)"
                    
                    current_guest_el = time_star_info['element']
                    current_guest_name = time_star_info['name'] + "(流年)"

                # 計算關係 (Host vs Guest)
                rel = get_element_relation(me=current_host_el, target=current_guest_el)
                
                trend_response["datasets"][name].append(rel["score"])
                grade_score = STAR_MODIFIERS.get(aspect_star_info['name'], 0)
                root_score = 10 if curr_idx in pillar_indices else 0
                trend_response["adjustments"][name].append(grade_score + root_score)
                
                trend_response["tooltips"][name].append(f"{current_guest_name} {rel['type']} {current_host_name}")
                
        return trend_response

    def check_risk(self, target_year):
        risks = []
        star = STARS_INFO[ZHI[self.hour_idx]]['name']
        if star in BAD_STARS: risks.append(f"命帶{star}")
        return risks

# ---------------- API 模型 ----------------
class UserRequest(BaseModel):
    gender: int; solar_date: str; hour: str; target_calendar: str = 'lunar'; target_scope: str = 'year'; target_year: int; target_month: int = 1; target_day: int = 1; target_hour: str = '子'
class AIRequest(BaseModel): prompt: str
class SaveRequest(BaseModel):
    solar_date: Optional[str] = None; gender: Optional[int] = None; hour: Optional[str] = None; target_year: Optional[int] = None
    client_name: Optional[str] = None; phone: Optional[str] = ""; tags: Optional[List[str]] = []
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
        target_data = parse_target_date(req.target_scope, req.target_calendar, req.target_year, req.target_month, req.target_day, req.target_hour)
        age = target_data['lunar_year'] - lunar_data['lunar_year_num'] + 1
        system = OnePalmSystem(req.gender, lunar_data['year_zhi'], lunar_data['month'], lunar_data['day'], req.hour)
        base_chart = system.get_base_chart()
        hierarchy = system.calculate_hierarchy(age, target_data, req.target_scope)
        aspects = []
        base_idx = get_zhi_index(hierarchy['year']['zhi']) if req.target_scope == 'year' else get_zhi_index(hierarchy['year']['zhi'])
        
        # 列表顯示的主客邏輯
        host_star = hierarchy['year'] 
        if req.target_scope == 'month': host_star = hierarchy['month']
        
        for i, name in enumerate(ASPECTS_ORDER):
            curr_idx = (base_idx + i) % 12 
            guest_star_info = STARS_INFO[ZHI[curr_idx]] 
            
            # 特案：總命運列表顯示同步
            current_host_el = host_star['element']
            if req.target_scope == 'year' and name == "總命運":
                current_host_el = hierarchy['big_luck']['element']

            rel = get_element_relation(me=current_host_el, target=guest_star_info['element'])
            
            aspects.append({
                "name": name, 
                "star": guest_star_info['name'], 
                "element": guest_star_info['element'], 
                "zhi": ZHI[curr_idx], 
                "relation": rel['type'], 
                "is_alert": (rel['type'] in ['我剋','剋我'])
            })
        
        trend_data = system.calculate_full_trend(hierarchy, req.target_scope, lunar_data, target_data, system)
        scope_map = {'year': '流年', 'month': '流月', 'day': '流日', 'hour': '流時'}
        ai_prompt = (f"案主{age}歲，目標{target_data['display_info']}，層級{scope_map.get(req.target_scope)}。")
        return {"lunar_info": lunar_data['lunar_str'], "age": age, "base_chart": base_chart, "hierarchy": hierarchy, "target_display": target_data['display_info'], "aspects": aspects, "ai_prompt": ai_prompt, "trend_data": trend_data}
    except Exception as e: logger.error(str(e)); raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/api/ask_ai")
async def ask_ai(req: AIRequest):
    if "請在此" in OPENAI_API_KEY: return {"error": "Key Error"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": req.prompt}])
        return {"reply": res.choices[0].message.content}
    except Exception as e: return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

