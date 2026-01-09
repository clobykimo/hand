import logging
import os
import sys
import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from borax.calendars.lunardate import LunarDate
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"

app = FastAPI(title="達摩一掌經命理戰略中台 - V5.9")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db = None
try:
    db = firestore.Client()
    logger.info("✅ Firestore 連線成功")
except Exception as e:
    logger.warning(f"⚠️ Firestore 連線失敗: {e}")

# ---------------- 知識庫 (分數定義) ----------------
ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
STARS_INFO = {
    '子': {'name': '天貴星', 'element': '水', 'realm': '佛道'}, '丑': {'name': '天厄星', 'element': '土', 'realm': '鬼道'},
    '寅': {'name': '天權星', 'element': '木', 'realm': '人道'}, '卯': {'name': '天破星', 'element': '木', 'realm': '畜道'},
    '辰': {'name': '天奸星', 'element': '土', 'realm': '修羅'}, '巳': {'name': '天文星', 'element': '火', 'realm': '仙道'},
    '午': {'name': '天福星', 'element': '火', 'realm': '佛道'}, '未': {'name': '天驛星', 'element': '土', 'realm': '鬼道'},
    '申': {'name': '天孤星', 'element': '金', 'realm': '人道'}, '酉': {'name': '天刃星', 'element': '金', 'realm': '畜道'},
    '戌': {'name': '天藝星', 'element': '土', 'realm': '修羅'}, '亥': {'name': '天壽星', 'element': '水', 'realm': '仙道'}
}
ASPECTS_ORDER = ["總命運", "形象", "幸福", "事業", "變動", "健慾", "愛情", "領導", "親信", "根基", "朋友", "錢財"]

# [V5.9] 分數結構定義
# 1. 星宿底氣 (Base): 基準分60 + 加減
STAR_BASE_SCORES = {
    '天貴星': 15, '天福星': 15, '天壽星': 10, '天文星': 10, # 吉星
    '天權星': 5,  '天藝星': 5,  '天驛星': 0,  '天奸星': -5, # 平星
    '天孤星': -10, '天刃星': -10, '天破星': -15, '天厄星': -20 # 凶星
}

# 2. 五行互動 (Element): 生剋分數
ELEMENT_SCORES_MAP = {
    "比旺": 10, "生我": 15, "我生": 5, "我剋": -5, "剋我": -15, "未知": 0
}

# 3. 十二宮品格 (Palace): 模擬宮位加權 (此處為範例邏輯)
# 邏輯：星宿五行 與 宮位地支五行 的關係
PALACE_SCORES_MAP = {
    "水": {"水":5, "木":5, "金":5, "火":-5, "土":-10}, # 水星入各宮
    "木": {"木":5, "火":5, "水":5, "土":-5, "金":-10},
    "火": {"火":5, "土":5, "木":5, "金":-5, "水":-10},
    "土": {"土":5, "金":5, "火":5, "水":-5, "木":-10},
    "金": {"金":5, "水":5, "土":5, "木":-5, "火":-10}
}
ZHI_ELEMENTS = {'子':'水', '亥':'水', '寅':'木', '卯':'木', '巳':'火', '午':'火', '申':'金', '酉':'金', '辰':'土', '戌':'土', '丑':'土', '未':'土'}

# ---------------- 核心函數 ----------------
def get_zhi_index(zhi_char):
    return ZHI.index(zhi_char) if zhi_char in ZHI else 0

def get_next_position(start_index, steps, direction=1):
    return (start_index + (steps * direction)) % 12

def get_element_relation(me, target):
    PRODUCING = {'水': '木', '木': '火', '火': '土', '土': '金', '金': '水'}
    CONTROLING = {'水': '火', '火': '金', '金': '木', '木': '土', '土': '水'}
    if me == target: return "比旺"
    if PRODUCING.get(target) == me: return "生我"
    if PRODUCING.get(me) == target: return "我生"
    if CONTROLING.get(me) == target: return "我剋"
    if CONTROLING.get(target) == me: return "剋我"
    return "未知"

def solar_to_one_palm_lunar(solar_date_str):
    try:
        y, m, d = map(int, solar_date_str.split('-'))
        lunar = LunarDate.from_solar_date(y, m, d)
        year_zhi_idx = (lunar.year - 4) % 12
        final_month = lunar.month
        if lunar.leap and lunar.day > 15: final_month += 1
        return {
            "year_zhi": ZHI[year_zhi_idx],
            "month": final_month,
            "day": lunar.day,
            "lunar_year_num": lunar.year,
            "lunar_str": f"農曆 {lunar.year}年 {('閏' if lunar.leap else '')}{lunar.month}月 {lunar.day}日"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail="日期錯誤")

def parse_target_date(mode, calendar_type, year, month, day, hour_zhi):
    try:
        target_lunar_year = year
        target_lunar_month = month
        target_lunar_day = day
        display_info = ""
        if calendar_type == 'solar':
            lunar = LunarDate.from_solar_date(year, month, day)
            target_lunar_year = lunar.year
            target_lunar_month = lunar.month
            target_lunar_day = lunar.day
            display_info = f"國曆 {year}-{month}-{day}"
        else:
            display_info = f"農曆 {year}-{month}-{day}"
        target_year_zhi = ZHI[(target_lunar_year - 4) % 12]
        return {
            "lunar_year": target_lunar_year, "lunar_month": target_lunar_month,
            "lunar_day": target_lunar_day, "year_zhi": target_year_zhi,
            "hour_zhi": hour_zhi, "display_info": display_info
        }
    except Exception:
        return {"lunar_year": year, "lunar_month": month, "lunar_day": day, "year_zhi": ZHI[(year-4)%12], "hour_zhi": hour_zhi, "display_info": ""}

class OnePalmSystem:
    def __init__(self, gender, birth_year_zhi, birth_month_num, birth_day_num, birth_hour_zhi):
        self.gender = gender
        self.direction = 1 if gender == 1 else -1
        self.year_idx = get_zhi_index(birth_year_zhi)
        self.month_idx = get_next_position(self.year_idx, birth_month_num - 1, self.direction)
        self.day_idx = get_next_position(self.month_idx, birth_day_num - 1, self.direction)
        self.hour_idx = get_next_position(self.day_idx, get_zhi_index(birth_hour_zhi), self.direction)

    def get_base_chart(self):
        chart = {}
        keys = [("年柱", self.year_idx, "父母宮"), ("月柱", self.month_idx, "事業宮"), 
                ("日柱", self.day_idx, "夫妻宮"), ("時柱", self.hour_idx, "命宮")]
        for key, idx, palace in keys:
            star = STARS_INFO[ZHI[idx]]
            chart[key] = {**star, "zhi": ZHI[idx], "name": star['name']}
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

    # [V5.9] 拆解分數回傳 (Base, Element, Palace)
    def calculate_full_trend(self, hierarchy, scope, lunar_data, target_data, system_obj):
        # 結構改變：components 存放三個分量
        trend_response = { "axis_labels": [], "components": {}, "tooltips": {} }
        
        for name in ASPECTS_ORDER:
            trend_response["components"][name] = {"star": [], "element": [], "palace": []}
            trend_response["tooltips"][name] = []

        loop_range = []
        if scope == 'year':
            current_target_year = target_data['lunar_year']
            for y in range(current_target_year - 6, current_target_year + 7):
                loop_range.append({'type': 'year', 'val': y, 'label': f"{y}"})
        elif scope == 'month':
            curr_lunar_year = target_data['lunar_year']
            for m in range(1, 13):
                try:
                    ld = LunarDate(curr_lunar_year, m, 1)
                    sd = ld.to_solar_date()
                    label_str = [f"農{m:02d}月", f"(國{sd.month}/{sd.day})"]
                except: label_str = f"{m}月"
                loop_range.append({'type': 'month', 'val': m, 'label': label_str})
        elif scope == 'day':
            curr_lunar_year = target_data['lunar_year']
            curr_lunar_month = target_data['lunar_month']
            days_in_month = 30
            try: LunarDate(curr_lunar_year, curr_lunar_month, 30)
            except: days_in_month = 29
            for d in range(1, days_in_month + 1):
                try:
                    ld = LunarDate(curr_lunar_year, curr_lunar_month, d)
                    sd = ld.to_solar_date()
                    label_str = [f"初{d}", f"({sd.month}/{sd.day})"]
                except: label_str = f"{d}日"
                loop_range.append({'type': 'day', 'val': d, 'label': label_str})
        else:
            for h_idx in range(12):
                times = ["23-01", "01-03", "03-05", "05-07", "07-09", "09-11", "11-13", "13-15", "15-17", "17-19", "19-21", "21-23"]
                label_str = [f"{ZHI[h_idx]}時", f"({times[h_idx]})"]
                loop_range.append({'type': 'hour', 'val': h_idx, 'label': label_str})

        for point in loop_range:
            trend_response["axis_labels"].append(point['label'])
            target_el = None; target_name = ""; current_anchor_idx = 0 
            
            # 定位邏輯 (同前)
            if scope == 'year':
                y_age = point['val'] - lunar_data['lunar_year_num'] + 1
                luck_stg = (y_age - 1) // 7
                start_luck = get_next_position(system_obj.hour_idx, 1, system_obj.direction)
                bl_idx = get_next_position(start_luck, luck_stg, system_obj.direction)
                target_el = STARS_INFO[ZHI[bl_idx]]['element']; target_name = "大運" + STARS_INFO[ZHI[bl_idx]]['name']
                y_zhi_idx = (point['val'] - 4) % 12
                fy_idx = get_next_position(bl_idx, y_zhi_idx, system_obj.direction)
                current_anchor_idx = fy_idx 
            elif scope == 'month':
                fy_idx = get_zhi_index(hierarchy['year']['zhi'])
                target_el = STARS_INFO[ZHI[fy_idx]]['element']; target_name = "流年" + STARS_INFO[ZHI[fy_idx]]['name']
                fm_idx = get_next_position(fy_idx, point['val'] - 1, system_obj.direction)
                current_anchor_idx = fm_idx
            elif scope == 'day':
                fm_idx = get_zhi_index(hierarchy['month']['zhi'])
                target_el = STARS_INFO[ZHI[fm_idx]]['element']; target_name = "流月" + STARS_INFO[ZHI[fm_idx]]['name']
                fd_idx = get_next_position(fm_idx, point['val'] - 1, system_obj.direction)
                current_anchor_idx = fd_idx
            else:
                fd_idx = get_zhi_index(hierarchy['day']['zhi'])
                target_el = STARS_INFO[ZHI[fd_idx]]['element']; target_name = "流日" + STARS_INFO[ZHI[fd_idx]]['name']
                fh_idx = get_next_position(fd_idx, point['val'], system_obj.direction)
                current_anchor_idx = fh_idx

            for i, name in enumerate(ASPECTS_ORDER):
                aspect_zhi_idx = (current_anchor_idx + i) % 12
                aspect_star_name = STARS_INFO[ZHI[aspect_zhi_idx]]['name']
                aspect_el = STARS_INFO[ZHI[aspect_zhi_idx]]['element']
                aspect_zhi = ZHI[aspect_zhi_idx]
                
                # 1. Star Base Score (星宿底氣)
                s_star = STAR_BASE_SCORES.get(aspect_star_name, 0)
                
                # 2. Element Score (五行互動)
                rel_type = get_element_relation(aspect_el, target_el)
                s_elem = ELEMENT_SCORES_MAP.get(rel_type, 0)
                
                # 3. Palace Score (十二宮品格)
                palace_el = ZHI_ELEMENTS[aspect_zhi]
                s_palace = PALACE_SCORES_MAP.get(aspect_el, {}).get(palace_el, 0)

                trend_response["components"][name]["star"].append(s_star)
                trend_response["components"][name]["element"].append(s_elem)
                trend_response["components"][name]["palace"].append(s_palace)
                
                tooltip = f"<b>{aspect_star_name}</b> (底氣{s_star:+})<br>" \
                          f"對{target_name}: {rel_type} ({s_elem:+})<br>" \
                          f"落{aspect_zhi}宮 ({s_palace:+})"
                trend_response["tooltips"][name].append(tooltip)

        return trend_response

# ---------------- API 模型與路由 (維持不變，僅 calculate 更新) ----------------
class UserRequest(BaseModel):
    gender: int; solar_date: str; hour: str; target_calendar: str = 'lunar'; target_scope: str = 'year'; target_year: int; target_month: int = 1; target_day: int = 1; target_hour: str = '子'
class AIRequest(BaseModel):
    prompt: str
class SaveRequest(BaseModel):
    solar_date: str; gender: int; hour: str; target_year: int; client_name: str = "未命名客戶"; phone: str = ""; tags: List[str] = []; note: str = ""; ai_log: Dict[str, Any] = {}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f: return f.read()
    return "<h1>系統啟動中</h1>"

@app.get("/crm", response_class=HTMLResponse)
async def read_crm():
    if os.path.exists("crm.html"):
        with open("crm.html", "r", encoding="utf-8") as f: return f.read()
    return "<h1>CRM 頁面建置中</h1>"

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
        base_idx = 0; target_env_star = None
        if req.target_scope == 'year': base_idx = get_zhi_index(hierarchy['year']['zhi']); target_env_star = hierarchy['big_luck'] 
        elif req.target_scope == 'month': base_idx = get_zhi_index(hierarchy['month']['zhi']); target_env_star = hierarchy['year'] 
        elif req.target_scope == 'day': base_idx = get_zhi_index(hierarchy['day']['zhi']); target_env_star = hierarchy['month'] 
        elif req.target_scope == 'hour': base_idx = get_zhi_index(hierarchy['hour']['zhi']); target_env_star = hierarchy['day'] 

        for i, name in enumerate(ASPECTS_ORDER):
            curr_idx = (base_idx + i) % 12 
            star_info = STARS_INFO[ZHI[curr_idx]]
            rel_type = get_element_relation(star_info['element'], target_env_star['element'])
            aspects.append({"name": name, "star": star_info['name'], "element": star_info['element'], "zhi": ZHI[curr_idx], "relation": rel_type, "is_alert": (rel_type == '剋我' or rel_type == '我剋')})

        trend_data = system.calculate_full_trend(hierarchy, req.target_scope, lunar_data, target_data, system)
        scope_map = {'year': '流年', 'month': '流月', 'day': '流日', 'hour': '流時'}
        ai_prompt = (f"案主{age}歲，目標{target_data['display_info']}，層級{scope_map.get(req.target_scope)}。")

        return {"lunar_info": lunar_data['lunar_str'], "age": age, "base_chart": base_chart, "hierarchy": hierarchy, "target_display": target_data['display_info'], "aspects": aspects, "ai_prompt": ai_prompt, "trend_data": trend_data}
    except Exception as e:
        logger.error(str(e)); raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ask_ai")
async def ask_ai(req: AIRequest):
    if not OPENAI_API_KEY or "請在此填入" in OPENAI_API_KEY: return {"error": "❌ API Key 未設定"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": req.prompt}])
        return {"reply": res.choices[0].message.content}
    except Exception as e: return {"error": str(e)}

@app.post("/api/save_record")
async def save_record(req: SaveRequest):
    if not db: return {"status": "error", "message": "資料庫未連接"}
    try:
        doc_ref = db.collection('consultations').document()
        data = req.dict(); data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(data)
        return {"status": "success", "id": doc_ref.id}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/search_records")
async def search_records(keyword: str = ""):
    if not db: return []
    try:
        docs = db.collection('consultations').order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        results = []
        for doc in docs:
            data = doc.to_dict(); data['id'] = doc.id
            if data.get('created_at'):
                dt = data['created_at']
                if hasattr(dt, 'timestamp'): data['created_at'] = datetime.datetime.fromtimestamp(dt.timestamp()).strftime("%Y-%m-%d %H:%M")
            if keyword:
                search_target = f"{data.get('client_name','')} {data.get('note','')} {str(data.get('tags',''))}"
                if keyword.lower() in search_target.lower(): results.append(data)
            else: results.append(data)
        return results
    except Exception as e: logger.error(str(e)); return []

@app.delete("/api/delete_record/{doc_id}")
async def delete_record(doc_id: str):
    if not db: return {"status": "error", "message": "DB error"}
    try:
        db.collection('consultations').document(doc_id).delete()
        return {"status": "success"}
    except Exception as e: return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
