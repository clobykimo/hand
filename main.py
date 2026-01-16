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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DamoSystem")

# ---------------- 設定區 ----------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "請在此填入您的OpenAI_API_Key"
SYSTEM_BASE_URL = "https://hand-316288530636.asia-east1.run.app"
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

app = FastAPI(title="達摩一掌經．生命藍圖導航系統 - V10.3 格局雷達版")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

db = None
try:
    db = firestore.Client()
    logger.info("✅ Firestore 連線成功")
except Exception as e:
    logger.warning(f"⚠️ Firestore 連線失敗: {e}")

# ---------------- [V10.3] 達摩知識庫核心 (詩訣與四柱詳解) ----------------
ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

STARS_INFO = {
    '子': {
        'name': '天貴星', 'element': '水', 'slogan': '春風化雨的清貴點燈人',
        'poem': '時辰落在天貴星，一生清貴事和同，志氣不凡人出類，安然自在性明通。',
        'pillars': {
            'year': '乖巧有人緣，心地善良，很會讀書，體貼父母，清雅高貴，重視內在人格涵養。',
            'month': '有貴人相助，適合以嘴巴來傳道，或從事文教清雅的工作，但不太積極。',
            'day': '女性較容易在婚姻生活中受苦，悟性強，常會有逃避現象，男性體貼溫柔。',
            'hour': '很有智慧，充滿慈悲心，重名不重利，自主性強，重於口德的佈施。'
        }
    },
    '丑': {
        'name': '天厄星', 'element': '土', 'slogan': '重見曙光的惜福者',
        'poem': '時在厄中人混沌，惺惺作事又癡呆，此人帶疾方延壽，還須辛勤工作生涯。',
        'pillars': {
            'year': '智慧不易開，怕孤獨寂寞，容易出意外，很孝順父母，幼年適合獎懲方式管教。',
            'month': '持續力差，無法收成安定，自主性弱，頗喜歡職場的熱鬧，容易滿足，不會抱怨。',
            'day': '婚姻無主見，困頓渾噩，但不適合單身，雖然苦也能忍受，不在意婚姻生活品質。',
            'hour': '生存力強，愛漂亮，心地好沒主見，不太用大腦，依賴性強，喜過美好日子。'
        }
    },
    '寅': {
        'name': '天權星', 'element': '木', 'slogan': '人生戰場，見我運籌帷幄',
        'poem': '時辰落在天權星，性格操持志氣雄，作事差遲人也喜，一呼百喏有威風。',
        'pillars': {
            'year': '從小很有主見，不喜歡被管束，年少容易嶄露頭角，具十足行動力。',
            'month': '衣食無虞，是主管的命格，愛掌權，主觀意識強烈，做事很有方法有效率。',
            'day': '會管另一半，為人處事一板一眼，頗會記仇，但都會放心中型。',
            'hour': '懂得經營，有很強的賺錢能量，不容易推心置腹，重視家庭生活，喜歡用錢堆積。'
        }
    },
    '卯': {
        'name': '天破星', 'element': '木', 'slogan': '守著陽光守著你',
        'poem': '時辰落在天破宮，堆金積玉也成空，夜眠算計圖家富，鈔袋誰知有蛀蟲。',
        'pillars': {
            'year': '個性保守，早年沒自信，義務型的孝順，幼年性格為乖乖牌，較沒勇氣與膽識。',
            'month': '適合上班族，沒有開創性，大部分的人一份工作都從事很久，且會邊做邊抱怨。',
            'day': '婚姻生活肯定不會太好，婚姻中會沒有自我，是愛家型的配偶，感情相當執著。',
            'hour': '個性溫和沒侵犯性，但防衛性很強，愛付出又心不甘情不願，無法享受生命。'
        }
    },
    '辰': {
        'name': '天奸星', 'element': '土', 'slogan': '山海中的精靈，別管我來去何方',
        'poem': '大如滄海細如毛，佛口蛇心兩面刀，姦狡狠謀藏毒性，意多翻覆最難調。',
        'pillars': {
            'year': '反叛性強，早期會被視為問題兒童，重感情及義氣，生命力強，可塑性相對低。',
            'month': '聰明但工作上的定性不夠，會常換工作，有創意，點子多，情緒掌握力差。',
            'day': '完美主義者，負責指揮家裏大小事，而且要視其情緒的掌控，但不記仇。',
            'hour': '反應快，很聰明，脾氣大，來得快去得也快，不信邪，很顧面子。'
        }
    },
    '巳': {
        'name': '天文星', 'element': '火', 'slogan': '浪漫唯美的性靈飛天女',
        'poem': '命遇天文秀氣清，聰明智慧意惺惺，男才女秀身清吉，滿腹文章錦繡成。',
        'pillars': {
            'year': '書讀得好，男性斯文，較無男性氣概，女性氣質柔美漂亮，唯獨感情上依賴很重。',
            'month': '研究學問高手，不能忍受髒亂的工作環境，也不能太辛苦，要學務實，公關人才。',
            'day': '喜歡幻想浪漫，重感覺，外遇機率高，女生不善家事，更要心靈的交流互動。',
            'hour': '愛漂亮，重感情，較沒定性個性充滿浪漫唯美，性聰明心細膩，是讀書料。'
        }
    },
    '午': {
        'name': '天福星', 'element': '火', 'slogan': '福佈施的善心大員外',
        'poem': '命逢天福是生時，定然倉庫有盈餘，寬洪大量根基穩，財帛光華百福齊。',
        'pillars': {
            'year': '略顯憨厚，逢凶化吉，與父母相處很好，貴人很多，有福報，經濟穩定。',
            'month': '常有貴人協助，易受提拔升官，沒什麼心眼，因事業順利，故較不積極。',
            'day': '女性苦難較多，不會撒嬌，男性因妻而貴，個性大而化之，比較慵懶，不懂體貼。',
            'hour': '性情憨厚，易相信別人，熱心大方，願意付出，繼續做財佈施。'
        }
    },
    '未': {
        'name': '天驛星', 'element': '土', 'slogan': '日夜奔馳，驛心難側',
        'poem': '人道若逢天驛星，搬移離祖不曾停，身心不得片時靜，走遍天涯是未寧。',
        'pillars': {
            'year': '與父母關係緣薄，從小就顯得很獨立，容易早出社會，心不易定。',
            'month': '習慣奔波，適合當導遊或各種業務性的工作，重視朋友感情，為人熱心。',
            'day': '婚後絕對會為家庭及對方付出，要慎選另一半，最好不要早婚。',
            'hour': '經常出國命，行動力強，重朋友愛熱鬧，要學習專心與靜心，怕鬼怪。'
        }
    },
    '申': {
        'name': '天孤星', 'element': '金', 'slogan': '人群中的獨孤隱人',
        'poem': '時辰若逢此天孤，六親兄弟有如無，空作空門清靜客，總有妻兒情分疏。',
        'pillars': {
            'year': '早年與父母關係較淡，不知如何與人互動，沉默寡言，書唸得並不是很好。',
            'month': '對金錢有深切自卑感，要學勇敢務實，常獨來獨往，較無創造力，要學習法佈施。',
            'day': '有冷漠的距離感，容易不解風情，冷戰可以持續很久，生活嚴謹。',
            'hour': '有自卑感害怕人群，行動力較弱，情緒容易卡在心中，理想性高。'
        }
    },
    '酉': {
        'name': '天刃星', 'element': '金', 'slogan': '盯緊目標伺機而動，唯我獨尊',
        'poem': '天刃為人性大剛，是非終日要爭強，持刀弄斧刑心重，好像將軍入戰場。',
        'pillars': {
            'year': '從小個性剛烈，常與父母產生衝突，對父母也很執著，氣管不好，具暴力傾向。',
            'month': '勇於冒險實踐，屬開路先鋒型，適合企業家和政客，容易中風。',
            'day': '性需求較強，敢愛敢恨，佔有慾強，最黏人，熱度也最高，霸氣的愛。',
            'hour': '剛強性急，很有行動力，做事果斷，目標取向，不拘小節，可多捐血。'
        }
    },
    '戌': {
        'name': '天藝星', 'element': '土', 'slogan': '藝高八斗，絕頂辯才',
        'poem': '天藝生人性最靈，將南作北逞多能，諱為見靈機關巧，到處和同作事勤。',
        'pillars': {
            'year': '幼年很有才華，主觀意識與能力都強，有藝術天份，較不能忍受父母的嘮叨。',
            'month': '適合從事專業性的工作，尤其理工方面，常常工作有成就，也可看得到具體結果。',
            'day': '希望配偶要有才華與能力，是心甘情願與對方結髮一輩子的人，但有時爭執性強。',
            'hour': '反應快，思緒敏銳，大都有特殊才能，固執不易說服，有我行我素之個性。'
        }
    },
    '亥': {
        'name': '天壽星', 'element': '水', 'slogan': '瀟灑、翩翩卻愛八卦的型男',
        'poem': '夫妻生時命最長，上恭下敬性溫良，一聞千悟心慈善，喜怒中間有主張。',
        'pillars': {
            'year': '孝順，貼心重感情，男生個性豪邁不拘小節，女生感覺像哥兒們。',
            'month': '適從事公關，不做勞力的活動，工作不定隨遇而安型，對外來沒有長遠計劃。',
            'day': '較重視另一半精神層面的溝通，怕挫折，感情依賴性頗強，很隨性，離婚率高。',
            'hour': '要理財並重務實，否則易抑鬱寡歡，容易有生殖系統的毛病。'
        }
    }
}

ASPECTS_ORDER = ["總命運", "形象", "幸福", "事業", "變動", "健康", "愛情", "領導", "親信", "根基", "朋友", "錢財"]
STAR_MODIFIERS = {'天貴星': 30, '天福星': 30, '天文星': 30, '天壽星': 30, '天權星': 10, '天藝星': 10, '天驛星': 10, '天奸星': 10, '天孤星': -20, '天破星': -20, '天刃星': -20, '天厄星': -20}
RENHE_MODIFIERS = {'天貴星': 10, '天福星': 10, '天文星': 10, '天壽星': 10, '天權星': 5, '天藝星': 5, '天驛星': 5, '天奸星': 5, '天孤星': -10, '天破星': -10, '天刃星': -10, '天厄星': -10}
BAD_STARS = ['天厄星', '天破星', '天刃星']

# ---------------- 核心函數 ----------------
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
        chart = {}; keys = [("年柱", self.year_idx, "year"), ("月柱", self.month_idx, "month"), ("日柱", self.day_idx, "day"), ("時柱", self.hour_idx, "hour")]
        for key, idx, p_key in keys: 
            star = STARS_INFO[ZHI[idx]]
            chart[key] = {
                "zhi": ZHI[idx], 
                "name": star['name'], 
                "element": star['element'],
                "slogan": star.get('slogan', ''),
                "poem": star.get('poem', ''),
                "desc": star['pillars'].get(p_key, '')
            }
        return chart

    # [V10.3] 新增：自動格局偵測雷達
    def calculate_special_patterns(self):
        patterns = []
        pillars = [self.year_idx, self.month_idx, self.day_idx, self.hour_idx]
        star_counts = {}
        
        # 1. 統計星宿出現次數 (犯重)
        for idx in pillars:
            star_name = STARS_INFO[ZHI[idx]]['name']
            star_counts[star_name] = star_counts.get(star_name, 0) + 1
            
        # 2. 判斷特殊格局 (依據一掌經總論)
        # [cite: 92] 四柱皆吉星者必大富大貴
        good_stars = ['天貴星', '天福星', '天壽星', '天文星', '天權星']
        if all(STARS_INFO[ZHI[idx]]['name'] in good_stars for idx in pillars):
            patterns.append({"name": "👑 四柱全吉格", "desc": "四柱皆為吉星，必然大富大貴之命。"})

        # [cite: 94] 四柱皆凶星
        bad_stars = ['天奸星', '天破星', '天驛星', '天刃星', '天厄星', '天孤星']
        if all(STARS_INFO[ZHI[idx]]['name'] in bad_stars for idx in pillars):
            patterns.append({"name": "⚠️ 四柱全凶格", "desc": "四柱皆凶，需修身養性，行善積德以化解。"})

        # [cite: 110] 三權若值者...富貴有權
        if star_counts.get('天權星', 0) >= 3:
            patterns.append({"name": "🔥 三權掌印格", "desc": "權星犯重，心高志大，富貴有權，不受人欺。"})
        
        # [cite: 111] 三貴若逢者...必然大貴
        if star_counts.get('天貴星', 0) >= 3:
            patterns.append({"name": "💎 三貴顯赫格", "desc": "貴星犯重，必然大貴，受人尊敬。"})

        # [cite: 113] 三福之人，必然大富
        if star_counts.get('天福星', 0) >= 3:
            patterns.append({"name": "💰 三福巨富格", "desc": "福星犯重，財源廣進，必然大富。"})

        # [cite: 104] 三孤...為僧道必成正果
        if star_counts.get('天孤星', 0) >= 3:
            patterns.append({"name": "🧘‍♂️ 三孤通靈格", "desc": "孤星犯重，若為僧道必成正果，在家亦非凡俗。"})

        # [cite: 106] 驛若三重，一生勞碌
        if star_counts.get('天驛星', 0) >= 3:
            patterns.append({"name": "🐎 三驛奔波格", "desc": "驛星犯重，一生勞碌，遷移無定。"})

        # [cite: 82] 二刃星者主慈善
        if star_counts.get('天刃星', 0) == 2:
            patterns.append({"name": "⚔️ 雙刃化善格", "desc": "刃星見二，反主慈善，但仍需修身。"})

        # [cite: 73] 逢三厄者不唯無厄，而衣祿有餘
        if star_counts.get('天厄星', 0) >= 3:
            patterns.append({"name": "🛡️ 三厄反吉格", "desc": "厄星犯重反不為厄，衣祿有餘。"})

        return patterns

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
        
        # [V10.3] 新增：計算特殊格局並回傳
        special_patterns = system.calculate_special_patterns()

        return {
            "lunar_info": lunar_data['lunar_str'], 
            "age": age, 
            "base_chart": base_chart, 
            "hierarchy": hierarchy, 
            "target_display": target_data['display_info'], 
            "dual_info": target_data.get('dual_info', {}), 
            "aspects": aspects, 
            "ai_prompt": "", 
            "trend_data": trend_data,
            "special_patterns": special_patterns  # [V10.3] 回傳格局
        }
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

@app.post("/api/ask_ai")
async def ask_ai(req: AIRequest):
    if "請在此" in OPENAI_API_KEY: return {"error": "API Key 未設定"}
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

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
        2. 說話風格：專業、理性、帶有戰略高度。
        3. 【古今對照指令】：若分析中涉及星宿，請務必【先引用古文詩訣】，再進行【現代白話戰略轉譯】，讓客戶既覺得有底蘊，又聽得懂。
        4. 【商業導購指令】：若發現低分 (<=40) 或凶格，請在結尾加上：「⚠ 偵測到此處能量波動較大，建議預約徐峰老師進行一對一深度佈局，以化解風險。」

        【當前案主數據】：
        - 年齡：{ctx.get('age', '未知')}
        - 目標時間：{ctx.get('target_display', '未知')}
        - 特殊格局：{str(ctx.get('special_patterns', []))}
        - 命盤重點數據：{str(ctx.get('aspects', []))}
        """

        messages = [{"role": "system", "content": system_prompt}]
        recent_history = req.history[-6:] 
        messages.extend(recent_history)
        messages.append({"role": "user", "content": req.message})

        res = client.chat.completions.create(
            model="gpt-4o", 
            messages=messages,
            temperature=0.7 
        )
        
        return {"reply": res.choices[0].message.content}

    except Exception as e:
        logger.error(f"AI Error: {str(e)}")
        return {"reply": f"AI 思考過載中，請稍後再試。({str(e)})"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
