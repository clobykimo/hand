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

app = FastAPI(title="達摩一掌經命理戰略中台 - V9.2 全維度戰略版")

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

# [V9.1] 五行生剋分數 (80/75/60/35/20)
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
        luck_stage = (current_age - 1) // 7 # 7年一運
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

    # [V9.2] 趨勢運算 (全維度支援 + 層級遞進主客法則)
    def calculate_full_trend(self, hierarchy, scope, lunar_data, target_data, system_obj):
        trend_response = { "axis_labels": [], "datasets": {}, "adjustments": {}, "renhe_scores": [], "tooltips": {} }
        for name in ASPECTS_ORDER: 
            trend_response["datasets"][name] = []; trend_response["adjustments"][name] = []; trend_response["tooltips"][name] = []
        
        # 1. 定義時間迴圈範圍 (X軸)
        loop_items = []
        
        if scope == 'year':
            # 流年模式：前後 6 年
            current_idx = get_zhi_index(hierarchy['year']['zhi'])
            base_year = target_data['lunar_year']
            for i in range(-6, 7):
                loop_items.append({'offset': i, 'label': f"{base_year + i}", 'type': 'year'})
                
        elif scope == 'month':
            # 流月模式：1-12 月
            # 基準點：當年流年星
            for i in range(1, 13):
                # offset 是相對於 "正月" 的偏移，所以是 i-1
                # 但這裡為了方便，我們直接記錄月份數，計算時再處理
                loop_items.append({'val': i, 'label': f"{i}月", 'type': 'month'})
                
        elif scope == 'day':
            # [新增] 流日模式：1-30 日 (簡單模擬農曆大小月，統一跑30天顯示趨勢)
            for i in range(1, 31):
                loop_items.append({'val': i, 'label': f"{i}日", 'type': 'day'})
                
        elif scope == 'hour':
            # [新增] 流時模式：12 時辰
            for z in ZHI:
                loop_items.append({'val': z, 'label': f"{z}時", 'type': 'hour'})

        # 2. 獲取定位基準點 (Base Anchor)
        # 用於推算 X 軸每個點的星宿
        current_fy_idx = get_zhi_index(hierarchy['year']['zhi']) # 流年星位置
        current_fm_idx = get_zhi_index(hierarchy['month']['zhi']) # 流月星位置
        current_fd_idx = get_zhi_index(hierarchy['day']['zhi'])   # 流日星位置
        
        pillar_indices = [system_obj.year_idx, system_obj.month_idx, system_obj.day_idx, system_obj.hour_idx]
        
        # 3. 執行迴圈運算
        for point in loop_items:
            trend_response["axis_labels"].append(point['label'])
            
            # --- A. 計算當前時間點的主星 (Time Star) ---
            time_star_info = None
            
            if scope == 'year':
                # 推算每年的流年星
                dynamic_idx = get_next_position(current_fy_idx, point['offset'], system_obj.direction)
                time_star_info = STARS_INFO[ZHI[dynamic_idx]]
                
            elif scope == 'month':
                # 推算每月的流月星 (基準: 流年)
                # 流月 = 流年 + (月-1)
                # current_fy_idx 已經是當年的流年位置
                # 但 hierarchy['month'] 是目標月。我們需要重算 loop 中的月。
                # 重新依據流年推算：
                offset = point['val'] - 1
                dynamic_idx = get_next_position(current_fy_idx, offset, system_obj.direction)
                time_star_info = STARS_INFO[ZHI[dynamic_idx]]
                
            elif scope == 'day':
                # 推算每日的流日星 (基準: 流月)
                # 流日 = 流月 + (日-1)
                offset = point['val'] - 1
                dynamic_idx = get_next_position(current_fm_idx, offset, system_obj.direction)
                time_star_info = STARS_INFO[ZHI[dynamic_idx]]
                
            elif scope == 'hour':
                # 推算每時的流時星 (基準: 流日)
                # 流時 = 流日 + 時辰Index
                h_idx = get_zhi_index(point['val'])
                dynamic_idx = get_next_position(current_fd_idx, h_idx, system_obj.direction)
                time_star_info = STARS_INFO[ZHI[dynamic_idx]]

            # 標準邏輯：主 (Me) = 當下的時間星 (Time Star)
            me_el = time_star_info['element'] 
            age_star_name = time_star_info['name']
            
            # 人和分 (L3)
            renhe_val = RENHE_MODIFIERS.get(age_star_name, 0)
            trend_response["renhe_scores"].append({"score": renhe_val, "star": age_star_name})

            # --- B. 計算十二宮位的互動 ---
            for i, name in enumerate(ASPECTS_ORDER):
                curr_idx = (system_obj.hour_idx + i) % 12
                aspect_star_info = STARS_INFO[ZHI[curr_idx]]
                
                current_guest_el = aspect_star_info['element']
                current_guest_name = aspect_star_info['name']
                
                current_host_el = me_el
                current_host_name = age_star_name

                # [特案 V9.2] 層級遞進主客法則 (Total Destiny Cascade)
                # 只有在項目為「總命運」時，我們切換「主 (Host)」為上一層級的環境
                if name == "總命運":
                    upper_level_star = None
                    upper_level_label = ""
                    
                    if scope == 'year':
                        # 年模式：主=大運
                        upper_level_star = hierarchy['big_luck']
                        upper_level_label = "(大運)"
                    elif scope == 'month':
                        # 月模式：主=流年
                        upper_level_star = hierarchy['year']
                        upper_level_label = "(流年)"
                    elif scope == 'day':
                        # 日模式：主=流月
                        upper_level_star = hierarchy['month']
                        upper_level_label = "(流月)"
                    elif scope == 'hour':
                        # 時模式：主=流日
                        upper_level_star = hierarchy['day']
                        upper_level_label = "(流日)"
                        
                    if upper_level_star:
                        current_host_el = upper_level_star['element']
                        current_host_name = upper_level_star['name'] + upper_level_label
                        
                        # 此時的客 (Guest) 就是當下的時間星 (因為總命運=當下)
                        current_guest_el = time_star_info['element']
                        current_guest_name = time_star_info['name'] + "(值星)"

                # 計算關係
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

# ---------------- API 模型 (保持不變) ----------------
class UserRequest(BaseModel):
    gender: int; solar_date: str; hour: str; target_calendar: str = 'lunar'; target_scope: str = 'year'; target_year: int; target_month: int = 1; target_day: int = 1; target_hour: str = '子'
class AIRequest(BaseModel): prompt: str
class SaveRequest(BaseModel):
    solar_date: Optional[str] = None; gender: Optional[int] = None; hour: Optional[str] = None; target_year: Optional[int] = None
    client_name: Optional[str] = None; phone: Optional[str] = ""; tags: Optional[List[str]] = []
    note: Optional[str] = ""; ai_log: Optional[Dict[str, Any]] = {}
    image_urls: Optional[List[str]] = []; audio_url: Optional[str] = ""; transcript: Optional[str] = ""
    relations: Optional[List[Dict[str, Any]]] = []; consent_signed: Optional[bool] = False; consent_date: Optional[str] = ""

# ---------------- API 路由 (保持不變) ----------------
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
        
        # 列表顯示的主客邏輯 (靜態顯示)
        host_star = hierarchy['year'] 
        if req.target_scope == 'month': host_star = hierarchy['month']
        elif req.target_scope == 'day': host_star = hierarchy['day']
        elif req.target_scope == 'hour': host_star = hierarchy['hour']
        
        for i, name in enumerate(ASPECTS_ORDER):
            curr_idx = (base_idx + i) % 12 
            guest_star_info = STARS_INFO[ZHI[curr_idx]] 
            
            # 靜態列表的特案邏輯 (與波形圖同步)
            current_host_el = host_star['element']
            if name == "總命運":
                if req.target_scope == 'year': current_host_el = hierarchy['big_luck']['element']
                elif req.target_scope == 'month': current_host_el = hierarchy['year']['element']
                elif req.target_scope == 'day': current_host_el = hierarchy['month']['element']
                elif req.target_scope == 'hour': current_host_el = hierarchy['day']['element']

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

# ... (其餘 API 保持不變) ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
