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

app = FastAPI(title="達摩一掌經命理戰略中台 - V7.9 最終整合版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Firestore 資料庫連線
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

# [V7.6] 三品格分數表 (天權恢復為 +10)
STAR_MODIFIERS = {
    # [上三品] 吉星 (+30)
    '天貴星': 30, '天福星': 30, '天文星': 30, '天壽星': 30,
    # [中三品] 平吉星 (+10)
    '天權星': 10, '天藝星': 10, '天驛星': 10, '天奸星': 10,
    # [下三品] 凶星 (-20)
    '天孤星': -20, '天破星': -20, '天刃星': -20, '天厄星': -20
}

BAD_STARS = ['天厄星', '天破星', '天刃星']

# ---------------- 核心函數 ----------------
def get_zhi_index(zhi_char): return ZHI.index(zhi_char) if zhi_char in ZHI else 0
def get_next_position(start_index, steps, direction=1): return (start_index + (steps * direction)) % 12

def get_element_relation(me, target):
    PRODUCING = {'水': '木', '木': '火', '火': '土', '土': '金', '金': '水'}
    CONTROLING = {'水': '火', '火': '金', '金': '木', '木': '土', '土': '水'}
    if me == target: return {"type": "比旺", "score": 85}
    if PRODUCING.get(target) == me: return {"type": "生我", "score": 95} 
    if PRODUCING.get(me) == target: return {"type": "我生", "score": 70}  
    if CONTROLING.get(me) == target: return {"type": "我剋", "score": 50}  
    if CONTROLING.get(target) == me: return {"type": "剋我", "score": 20}
    return {"type": "未知", "score": 50}

def solar_to_one_palm_lunar(solar_date_str):
    try:
        y, m, d = map(int, solar_date_str.split('-'))
        lunar = LunarDate.from_solar_date(y, m, d)
        year_zhi_idx = (lunar.year - 4) % 12
        final_month = lunar.month
        if lunar.leap and lunar.day > 15: final_month += 1
        return {"year_zhi": ZHI[year_zhi_idx], "month": final_month, "day": lunar.day, "lunar_year_num": lunar.year, "lunar_str": f"農曆 {lunar.year}年 {('閏' if lunar.leap else '')}{lunar.month}月 {lunar.day}日"}
    except: return None

# [V7.8] 日期解析 (雙曆並顯版)
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
            display_info = f"國曆 {year}-{month}-{day} (農曆 {lunar.year}年{lunar.month}月{lunar.day}日)"
        else:
            lunar_obj = LunarDate(year, month, day)
            solar_obj = lunar_obj.to_solar_date()
            target_lunar_year = year
            target_lunar_month = month
            target_lunar_day = day
            display_info = f"農曆 {year}年{month}月{day}日 (國曆 {solar_obj.year}-{solar_obj.month}-{solar_obj.day})"

        return {
            "lunar_year": target_lunar_year, 
            "lunar_month": target_lunar_month, 
            "lunar_day": target_lunar_day, 
            "year_zhi": ZHI[(target_lunar_year - 4) % 12], 
            "hour_zhi": hour_zhi, 
            "display_info": display_info
        }
    except Exception as e:
        return {
            "lunar_year": year, 
            "lunar_month": month, 
            "lunar_day": day, 
            "year_zhi": ZHI[(year-4)%12], 
            "hour_zhi": hour_zhi, 
            "display_info": f"{'國曆' if calendar_type=='solar' else '農曆'} {year}-{month}-{day} (轉換誤差)"
        }

class OnePalmSystem:
    def __init__(self, gender, birth_year_zhi, birth_month_num, birth_day_num, birth_hour_zhi):
        self.gender = gender; self.direction = 1 if gender ==
