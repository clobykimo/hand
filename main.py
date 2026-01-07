import logging
import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from borax.calendars.lunardate import LunarDate
from google.cloud import firestore
import datetime

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

# ==========================================
# 請在此填入您的 OpenAI API Key (或設定環境變數)
# ==========================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"

app = FastAPI(title="達摩一掌經命理戰略中台 - V5.6 CRM旗艦版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- 資料庫初始化 ----------------
db = None
try:
    db = firestore.Client()
    logger.info("✅ Firestore 連線成功")
except Exception as e:
    logger.warning(f"⚠️ Firestore 連線失敗 (若是本地測試請忽略): {e}")

# ---------------- 知識庫 ----------------
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

# 十二宮三品格加權分數
STAR_MODIFIERS = {
    '天貴星': 30, '天厄星': -30, '天權星': 20, '天破星': -20,
    '天奸星': -30, '天文星': 0, '天福星': 30, '天驛星': 0,
    '天孤星': -20, '天刃星': 0, '天藝星': 0, '天壽星': 20
}

# ---------------- 核心函數 ----------------
def get_zhi_index(zhi_char):
    return ZHI.index(zhi_char) if zhi_char in ZHI else 0

def get_next_position(start_index, steps, direction=1):
    return (start_index + (steps * direction)) % 12

def get_element_relation(me, target):
    # Me = 主動方 (流年/流月/流日/流時)
    # Target = 被動方 (大運/流年/流月/流日)
    PRODUCING = {'水': '木', '木': '火', '火': '土', '土': '金', '金': '水'}
    CONTROLING = {'水': '火', '火': '金', '金': '木', '木': '土', '土': '水'}
    
    if me == target: return {"type": "比旺", "score": 95, "alert": False}
    if PRODUCING.get(target) == me: return {"type": "生我", "score": 80, "alert": False} 
    if PRODUCING.get(me) == target: return {"type": "我生", "score": 75, "alert": False}  
    if CONTROLING.get(me) == target: return {"type": "我剋", "score": 55, "alert": True}  
    if CONTROLING.get(target) == me: return {"type": "剋我", "score": 5, "alert": True} # 風險極值
    return {"type": "未知", "score": 50, "alert": False}

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

# ---------------- 一掌經系統類別 ----------------
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

# [V5.7] 針對所有運程計算趨勢 (含雙曆標註)
    def calculate_full_trend(self, hierarchy, scope, lunar_data, target_data, system_obj):
        trend_response = { 
            "axis_labels": [], "datasets": {}, "adjustments": {}, "tooltips": {} 
        }
        for name in ASPECTS_ORDER:
            trend_response["datasets"][name] = []
            trend_response["adjustments"][name] = []
            trend_response["tooltips"][name] = []

        loop_range = []
        
        # --- [關鍵修改] 建立時間軸與雙曆標籤 ---
        
        if scope == 'year':
            # 流年：前後 6 年 (共13點) - 年份差異不大，直接顯示數字
            current_target_year = target_data['lunar_year']
            for y in range(current_target_year - 6, current_target_year + 7):
                # 簡單加上生肖或是西元
                # 這裡的 y 是農曆年，但通常與西元轉換只差不到一個月，直接顯示西元即可
                loop_range.append({'type': 'year', 'val': y, 'label': f"{y}"})
                
        elif scope == 'month':
            # 流月：顯示 當年12個月 (為了對應清楚，我們先鎖定當年)
            # 若要跨年太複雜，我們先優化「當年」的顯示
            # 我們計算當年農曆 1~12 月，每個月初一對應的國曆日期
            
            # 取得當前農曆年
            curr_lunar_year = target_data['lunar_year']
            
            for m in range(1, 13):
                # 將 農曆年/月/1日 轉為 國曆
                try:
                    # borax 的 LunarDate
                    ld = LunarDate(curr_lunar_year, m, 1)
                    sd = ld.to_solar_date() # 轉回國曆
                    # 格式：農01 (國02/17)
                    label_str = [f"農{m:02d}月", f"(國{sd.month}/{sd.day})"] # 陣列會讓 Chart.js 換行
                except:
                    label_str = f"{m}月"
                
                loop_range.append({'type': 'month', 'val': m, 'label': label_str})

        elif scope == 'day':
            # 流日：當月 1~30 日 (或29日)
            curr_lunar_year = target_data['lunar_year']
            curr_lunar_month = target_data['lunar_month']
            
            # 判斷該月有幾天 (29 或 30)
            days_in_month = 30 # 簡單預設，borax 其實可以算，但為求穩健先跑30
            try:
                # 嘗試建立第30天，若失敗代表只有29天
                LunarDate(curr_lunar_year, curr_lunar_month, 30)
            except:
                days_in_month = 29

            for d in range(1, days_in_month + 1):
                try:
                    ld = LunarDate(curr_lunar_year, curr_lunar_month, d)
                    sd = ld.to_solar_date()
                    # 格式：初一 (02/17)
                    label_str = [f"初{d}", f"({sd.month}/{sd.day})"]
                except:
                    label_str = f"{d}日"
                
                loop_range.append({'type': 'day', 'val': d, 'label': label_str})

        else: 
            # 流時
            for h_idx in range(12):
                # 流時對應的現代時間 (概略)
                times = ["23-01", "01-03", "03-05", "05-07", "07-09", "09-11", 
                         "11-13", "13-15", "15-17", "17-19", "19-21", "21-23"]
                label_str = [f"{ZHI[h_idx]}時", f"({times[h_idx]})"]
                loop_range.append({'type': 'hour', 'val': h_idx, 'label': label_str})

        # --- 以下維持原有的運算邏輯 ---
        for point in loop_range:
            trend_response["axis_labels"].append(point['label'])
            me_el = None; target_el = None; target_name = ""; current_anchor_idx = 0 

            if scope == 'year':
                y_age = point['val'] - lunar_data['lunar_year_num'] + 1
                luck_stg = (y_age - 1) // 7
                start_luck = get_next_position(system_obj.hour_idx, 1, system_obj.direction)
                bl_idx = get_next_position(start_luck, luck_stg, system_obj.direction)
                target_el = STARS_INFO[ZHI[bl_idx]]['element']
                target_name = "大運" + STARS_INFO[ZHI[bl_idx]]['name']
                y_zhi_idx = (point['val'] - 4) % 12
                fy_idx = get_next_position(bl_idx, y_zhi_idx, system_obj.direction)
                me_el = STARS_INFO[ZHI[fy_idx]]['element']
                current_anchor_idx = fy_idx 

            elif scope == 'month':
                fy_idx = get_zhi_index(hierarchy['year']['zhi'])
                target_el = STARS_INFO[ZHI[fy_idx]]['element']
                target_name = "流年" + STARS_INFO[ZHI[fy_idx]]['name']
                fm_idx = get_next_position(fy_idx, point['val'] - 1, system_obj.direction)
                me_el = STARS_INFO[ZHI[fm_idx]]['element']
                current_anchor_idx = fm_idx

            elif scope == 'day':
                fm_idx = get_zhi_index(hierarchy['month']['zhi'])
                target_el = STARS_INFO[ZHI[fm_idx]]['element']
                target_name = "流月" + STARS_INFO[ZHI[fm_idx]]['name']
                fd_idx = get_next_position(fm_idx, point['val'] - 1, system_obj.direction)
                me_el = STARS_INFO[ZHI[fd_idx]]['element']
                current_anchor_idx = fd_idx

            else: # hour
                fd_idx = get_zhi_index(hierarchy['day']['zhi'])
                target_el = STARS_INFO[ZHI[fd_idx]]['element']
                target_name = "流日" + STARS_INFO[ZHI[fd_idx]]['name']
                fh_idx = get_next_position(fd_idx, point['val'], system_obj.direction)
                me_el = STARS_INFO[ZHI[fh_idx]]['element']
                current_anchor_idx = fh_idx

            for i, name in enumerate(ASPECTS_ORDER):
                aspect_zhi_idx = (current_anchor_idx + i) % 12
                aspect_star_name = STARS_INFO[ZHI[aspect_zhi_idx]]['name']
                aspect_el = STARS_INFO[ZHI[aspect_zhi_idx]]['element']
                
                rel = get_element_relation(aspect_el, target_el)
                trend_response["datasets"][name].append(rel["score"])
                mod_score = STAR_MODIFIERS.get(aspect_star_name, 0)
                trend_response["adjustments"][name].append(mod_score)
                trend_response["tooltips"][name].append(f"對{target_name} ({rel['type']})<br>坐{aspect_star_name} ({'+' if mod_score>0 else ''}{mod_score})")

        return trend_response

# ---------------- API 模型 ----------------
class UserRequest(BaseModel):
    gender: int
    solar_date: str 
    hour: str       
    target_calendar: str = 'lunar'
    target_scope: str = 'year'
    target_year: int
    target_month: int = 1
    target_day: int = 1
    target_hour: str = '子'

class AIRequest(BaseModel):
    prompt: str

# [V5.6] CRM 資料模型
class SaveRequest(BaseModel):
    # 基礎還原
    solar_date: str
    gender: int
    hour: str
    target_year: int
    # CRM
    client_name: str = "未命名客戶"
    phone: str = ""
    tags: List[str] = []
    note: str = ""
    # AI 洞察
    ai_log: Dict[str, Any] = {} 

# ---------------- API 路由 ----------------
@app.get("/", response_class=HTMLResponse)
async def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>系統啟動中，請確認 index.html 存在</h1>"

@app.post("/api/calculate")
async def calculate(req: UserRequest):
    try:
        lunar_data = solar_to_one_palm_lunar(req.solar_date)
        target_data = parse_target_date(
            req.target_scope, req.target_calendar, 
            req.target_year, req.target_month, req.target_day, req.target_hour
        )
        age = target_data['lunar_year'] - lunar_data['lunar_year_num'] + 1
        
        system = OnePalmSystem(req.gender, lunar_data['year_zhi'], lunar_data['month'], lunar_data['day'], req.hour)
        base_chart = system.get_base_chart()
        hierarchy = system.calculate_hierarchy(age, target_data, req.target_scope)
        
        final_star_info = hierarchy[req.target_scope]
        aspects = []
        base_idx = 0
        target_env_star = None
        
        if req.target_scope == 'year':
            base_idx = get_zhi_index(hierarchy['year']['zhi'])
            target_env_star = hierarchy['big_luck'] 
        elif req.target_scope == 'month':
            base_idx = get_zhi_index(hierarchy['month']['zhi'])
            target_env_star = hierarchy['year'] 
        elif req.target_scope == 'day':
            base_idx = get_zhi_index(hierarchy['day']['zhi'])
            target_env_star = hierarchy['month'] 
        elif req.target_scope == 'hour':
            base_idx = get_zhi_index(hierarchy['hour']['zhi'])
            target_env_star = hierarchy['day'] 

        for i, name in enumerate(ASPECTS_ORDER):
            curr_idx = (base_idx + i) % 12 
            star_info = STARS_INFO[ZHI[curr_idx]]
            rel = get_element_relation(star_info['element'], target_env_star['element'])
            aspects.append({
                "name": name, "star": star_info['name'], "element": star_info['element'],
                "zhi": ZHI[curr_idx], "relation": rel['type'], "is_alert": rel['alert']
            })

        trend_data = system.calculate_full_trend(hierarchy, req.target_scope, lunar_data, target_data, system)

        scope_map = {'year': '流年', 'month': '流月', 'day': '流日', 'hour': '流時'}
        ai_prompt = (f"案主{age}歲，目標{target_data['display_info']}，"
                     f"層級{scope_map.get(req.target_scope)}。")

        return {
            "lunar_info": lunar_data['lunar_str'], "age": age, 
            "base_chart": base_chart, "hierarchy": hierarchy, 
            "target_display": target_data['display_info'],
            "aspects": aspects, "ai_prompt": ai_prompt,
            "trend_data": trend_data 
        }
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ask_ai")
async def ask_ai(req: AIRequest):
    if not OPENAI_API_KEY or "請在此填入" in OPENAI_API_KEY:
        return {"error": "❌ API Key 未設定"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": req.prompt}])
        return {"reply": res.choices[0].message.content}
    except Exception as e:
        return {"error": str(e)}

# [API] 儲存紀錄 (CRM + AI Insight)
@app.post("/api/save_record")
async def save_record(req: SaveRequest):
    if not db:
        return {"status": "error", "message": "資料庫未連接"}
    try:
        doc_ref = db.collection('consultations').document()
        data = req.dict()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref.set(data)
        return {"status": "success", "id": doc_ref.id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# [API] 讀取歷史
@app.get("/api/get_history")
async def get_history():
    if not db: return []
    try:
        docs = db.collection('consultations').order_by('created_at', direction=firestore.Query.DESCENDING).limit(15).stream()
        history = []
        for doc in docs:
            data = doc.to_dict()
            if data.get('created_at'):
                # 轉為本地時間字串
                dt = data['created_at']
                if hasattr(dt, 'timestamp'): 
                    data['created_at'] = datetime.datetime.fromtimestamp(dt.timestamp()).strftime("%Y-%m-%d %H:%M")
            history.append(data)
        return history
    except Exception as e:
        logger.error(str(e))
        return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

