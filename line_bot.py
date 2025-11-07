#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LINE Bot - 最終修正版
🔥 關鍵修正：時間戳記計算不使用時區
"""

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import os
import datetime
import re
import threading
import requests
import hmac
import hashlib
import time
from typing import Dict, Optional
from zoneinfo import ZoneInfo

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LIFF_ID = os.getenv('LIFF_ID', '')
API_KEY = os.getenv('API_KEY', '')
API_SECRET = os.getenv('API_SECRET', '')
STATION_ID = os.getenv('STATION_ID', '')
MOENV_API_TOKEN = os.getenv('MOENV_API_TOKEN', '')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_states = {}

TW_TZ = ZoneInfo("Asia/Taipei")

AIRLINK_LSIDS = {
    652269: "南區上",
    655484: "南區下"
}

# ==================== Historic API（修正版）====================

def generate_signature(api_key, api_secret, t, station_id, start_ts, end_ts):
    """與 Streamlit 相同的簽名函數"""
    parts = [
        "api-key", api_key, 
        "end-timestamp", str(end_ts), 
        "start-timestamp", str(start_ts), 
        "station-id", str(station_id), 
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()

def fetch_airlink_historical(api_key, api_secret, station_id, start_ts, end_ts):
    """與 Streamlit 相同的 API 呼叫"""
    t = int(time.time())
    signature = generate_signature(api_key, api_secret, t, station_id, start_ts, end_ts)
    url = f"https://api.weatherlink.com/v2/historic/{station_id}"
    params = {
        "api-key": api_key, 
        "t": t, 
        "start-timestamp": start_ts, 
        "end-timestamp": end_ts, 
        "api-signature": signature
    }
    
    print(f"📡 API 請求: start={start_ts}, end={end_ts}")
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        print(f"   狀態: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"   ❌ 錯誤: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"   ❌ 異常: {e}")
        return None

def query_historical_data(api_key, api_secret, station_id, start_date, end_date):
    """
    歷史資料查詢
    🔥 關鍵修正：不使用時區計算時間戳記
    """
    try:
        print(f"🔍 查詢: {start_date} ~ {end_date}")
        
        # 🔥 重要：不加 tzinfo
        # datetime.combine() 產生 naive datetime
        # timestamp() 會將其視為本地時間並正確轉換為 UTC
        start_dt = datetime.datetime.combine(start_date, datetime.time.min)
        end_dt = datetime.datetime.combine(end_date, datetime.time.min)
        end_dt_fetch = end_dt + datetime.timedelta(days=1)
        
        all_records = []
        current_dt = start_dt
        
        # 逐日查詢
        while current_dt < end_dt_fetch:
            next_dt = min(current_dt + datetime.timedelta(days=1), end_dt_fetch)
            start_ts = int(current_dt.timestamp())
            end_ts = int(next_dt.timestamp())
            
            print(f"📅 查詢: {current_dt.date()}")
            
            data = fetch_airlink_historical(api_key, api_secret, station_id, start_ts, end_ts)
            
            if data:
                sensors = data.get("sensors", [])
                for sensor in sensors:
                    lsid = sensor.get("lsid")
                    if lsid not in AIRLINK_LSIDS:
                        continue
                    
                    device_name = AIRLINK_LSIDS[lsid]
                    sensor_data = sensor.get("data", [])
                    
                    print(f"   {device_name}: {len(sensor_data)} 筆")
                    
                    for record in sensor_data:
                        ts = record.get("ts")
                        if not ts:
                            continue
                        
                        # 🔥 格式化時使用 TW_TZ（顯示用）
                        timestamp = datetime.datetime.fromtimestamp(ts, tz=TW_TZ)
                        date_str = timestamp.strftime("%Y/%m/%d")
                        
                        pm25 = record.get("pm_2p5_avg") or record.get("pm_2p5") or record.get("pm_2p5_last")
                        pm10 = record.get("pm_10_avg") or record.get("pm_10") or record.get("pm_10_last")
                        
                        if pm25 is not None or pm10 is not None:
                            all_records.append({
                                "device": device_name,
                                "date": date_str,
                                "PM2.5": round(pm25, 1) if pm25 else None,
                                "PM10": round(pm10, 1) if pm10 else None
                            })
            
            current_dt = next_dt
            time.sleep(0.5)  # 避免 API rate limit
        
        if not all_records:
            return f"❌ {start_date} ~ {end_date} 期間無資料"
        
        # 計算每日平均
        daily_avg = {}
        for record in all_records:
            key = (record["device"], record["date"])
            if key not in daily_avg:
                daily_avg[key] = {"pm25": [], "pm10": []}
            
            if record["PM2.5"]:
                daily_avg[key]["pm25"].append(record["PM2.5"])
            if record["PM10"]:
                daily_avg[key]["pm10"].append(record["PM10"])
        
        # 格式化訊息
        message = f"📅 查詢期間: {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')}\n\n"
        message += "📊 每日平均值\n━━━━━━━━━━━━━━━\n\n"
        
        dates = sorted(set(record["date"] for record in all_records))
        
        for date_str in dates:
            parts = date_str.split('/')
            year_roc = int(parts[0]) - 1911
            date_roc = f"{year_roc}/{parts[1]}/{parts[2]}"
            
            message += f"【{date_roc}】\n"
            
            for device in ["南區上", "南區下"]:
                key = (device, date_str)
                if key in daily_avg:
                    pm25_list = daily_avg[key]["pm25"]
                    pm10_list = daily_avg[key]["pm10"]
                    
                    pm25_avg = round(sum(pm25_list) / len(pm25_list)) if pm25_list else None
                    pm10_avg = round(sum(pm10_list) / len(pm10_list)) if pm10_list else None
                    
                    pm25_str = str(pm25_avg) if pm25_avg else "--"
                    pm10_str = str(pm10_avg) if pm10_avg else "--"
                    
                    message += f"  {device}: PM2.5={pm25_str}, PM10={pm10_str}\n"
            message += "\n"
        
        message += "━━━━━━━━━━━━━━━\nℹ️ 資料來源：AirLink"
        
        print(f"✅ 查詢完成: {len(all_records)} 筆資料")
        return message
        
    except Exception as e:
        print(f"❌ 查詢異常: {e}")
        import traceback
        traceback.print_exc()
        return f"❌ 查詢失敗: {str(e)}"

def query_historical_async(user_id, start_date, end_date):
    """背景執行查詢"""
    try:
        result = query_historical_data(API_KEY, API_SECRET, STATION_ID, start_date, end_date)
        
        # 分段傳送（如果太長）
        if len(result) > 4500:
            parts = []
            current = ""
            for line in result.split('\n'):
                if len(current) + len(line) + 1 < 4500:
                    current += line + '\n'
                else:
                    parts.append(current)
                    current = line + '\n'
            if current:
                parts.append(current)
            
            for i, part in enumerate(parts):
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(
                        text=part,
                        quick_reply=create_main_menu_quick_reply() if i == len(parts)-1 else None
                    )
                )
        else:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=result, quick_reply=create_main_menu_quick_reply())
            )
            
    except Exception as e:
        print(f"❌ 背景查詢異常: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"❌ 查詢失敗: {str(e)}", quick_reply=create_main_menu_quick_reply())
        )

# ==================== Current API ====================

def generate_current_signature(api_key, api_secret, t, station_id):
    parts = ["api-key", api_key, "station-id", str(station_id), "t", str(t)]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()

def get_current_airlink_data(api_key, api_secret, station_id):
    try:
        t = int(time.time())
        signature = generate_current_signature(api_key, api_secret, t, station_id)
        url = f"https://api.weatherlink.com/v2/current/{station_id}"
        params = {"api-key": api_key, "t": t, "api-signature": signature}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            result = {}
            current_time = datetime.datetime.now(TW_TZ)
            
            for sensor in data.get("sensors", []):
                lsid = sensor.get("lsid")
                if lsid in AIRLINK_LSIDS:
                    station_name = AIRLINK_LSIDS[lsid]
                    sensor_data = sensor.get("data", [])
                    if sensor_data:
                        latest = sensor_data[0]
                        pm25 = latest.get("pm_2p5_last") or latest.get("pm_2p5")
                        pm10 = latest.get("pm_10_last") or latest.get("pm_10")
                        data_ts = latest.get("ts")
                        
                        if data_ts:
                            data_time = datetime.datetime.fromtimestamp(data_ts, tz=TW_TZ)
                            time_label = data_time.strftime("%m/%d %H:%M")
                        else:
                            time_label = current_time.strftime("%m/%d %H:%M")
                        
                        if pm25 is not None or pm10 is not None:
                            result[station_name] = {
                                "PM2.5": round(pm25, 1) if pm25 else None,
                                "PM10": round(pm10, 1) if pm10 else None,
                                "time": time_label
                            }
            return result if result else None
        return None
    except Exception as e:
        print(f"❌ Current API 錯誤: {e}")
        return None

def clean_concentration(value):
    if not value:
        return None
    value_str = str(value).strip()
    invalid_markers = ['#', '*', 'x', 'A', 'NR', 'ND', '', '-']
    if value_str in invalid_markers or any(m in value_str for m in invalid_markers if m):
        return None
    try:
        numeric_value = float(value_str)
        return numeric_value if 0 <= numeric_value <= 1000 else None
    except:
        return None

def get_current_moenv_data(api_token):
    try:
        url = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
        params = {"api_key": api_token, "limit": 100, "format": "json"}
        response = requests.get(url, params=params, timeout=10, verify=False)
        
        if response.status_code == 200:
            result = {}
            for record in response.json().get("records", []):
                site_name = record.get("sitename", "")
                if site_name in ["仁武", "楠梓"]:
                    pm25 = clean_concentration(record.get("pm2.5", ""))
                    pm10 = clean_concentration(record.get("pm10", ""))
                    
                    if pm25 is not None or pm10 is not None:
                        publish_time = record.get("publishtime", "")
                        try:
                            dt = datetime.datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                            time_str = dt.strftime("%m/%d %H:%M")
                        except:
                            time_str = publish_time
                        
                        result[site_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_str
                        }
            return result if result else None
        return None
    except Exception as e:
        print(f"❌ 環保署錯誤: {e}")
        return None

def get_aqi_level(pm25_value):
    if pm25_value is None:
        return "❓ 無資料", ""
    try:
        pm25 = float(pm25_value)
        if pm25 <= 15:
            return "😊 優良", "#00E400"
        elif pm25 <= 30:
            return "🙂 良好", "#FFFF00"
        elif pm25 <= 50:
            return "😐 普通", "#FF7E00"
        elif pm25 <= 100:
            return "😷 不良", "#FF0000"
        else:
            return "☠️ 非常不良", "#7E0023"
    except:
        return "❓ 無資料", ""

def format_air_quality_message(data):
    if not data:
        return "❌ 無法取得資料"
    
    current_time = datetime.datetime.now(TW_TZ).strftime("%m/%d %H:%M")
    message = f"🕐 查詢時間: {current_time}\n\n📊 最新空氣品質\n━━━━━━━━━━━━━━━\n\n"
    
    for station in ["仁武", "楠梓", "南區上", "南區下"]:
        if station in data:
            values = data[station]
            pm25 = values.get("PM2.5")
            pm10 = values.get("PM10")
            time_str = values.get("time", "")
            level, _ = get_aqi_level(pm25)
            
            message += f"📍 {station}\n"
            if pm25 is not None:
                exceed = " ⚠️" if pm25 > 30 else ""
                message += f"  PM2.5: {pm25} μg/m³{exceed}  {level}\n"
            else:
                message += f"  PM2.5: -- μg/m³\n"
            
            if pm10 is not None:
                exceed = " ⚠️" if pm10 > 75 else ""
                message += f"  PM10:  {pm10} μg/m³{exceed}\n"
            else:
                message += f"  PM10:  -- μg/m³\n"
            
            if time_str:
                message += f"  📝 資料時間: {time_str}\n"
            message += "\n"
    
    message += "━━━━━━━━━━━━━━━\n📌 法規標準（24小時平均值）\n• PM2.5 ≤ 30 μg/m³\n• PM10  ≤ 75 μg/m³\n\nℹ️ 資料來源：AirLink、環保署"
    return message

# ==================== LINE Bot ====================

def create_main_menu_quick_reply():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="📊 今日空品", text="今日")),
        QuickReplyButton(action=MessageAction(label="📅 歷史查詢", text="歷史查詢")),
        QuickReplyButton(action=MessageAction(label="🌐 開啟系統", text="開啟查詢系統"))
    ])

def create_date_range_examples_quick_reply():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="昨天", text=f"{yesterday.strftime('%Y/%m/%d')}-{yesterday.strftime('%Y/%m/%d')}")),
        QuickReplyButton(action=MessageAction(label="最近3天", text=f"{(today-datetime.timedelta(days=3)).strftime('%Y/%m/%d')}-{yesterday.strftime('%Y/%m/%d')}")),
        QuickReplyButton(action=MessageAction(label="取消", text="選單"))
    ])

def parse_date_range(text):
    try:
        text = text.strip()
        pattern1 = r'(\d{3,4})/(\d{1,2})/(\d{1,2})-(\d{3,4})/(\d{1,2})/(\d{1,2})'
        match = re.match(pattern1, text)
        if match:
            y1, m1, d1, y2, m2, d2 = match.groups()
            y1, y2 = int(y1), int(y2)
            if y1 < 1000:
                y1 += 1911
            if y2 < 1000:
                y2 += 1911
            return (datetime.date(y1, int(m1), int(d1)), datetime.date(y2, int(m2), int(d2)))
        
        pattern2 = r'(\d{1,2})/(\d{1,2})-(\d{1,2})/(\d{1,2})'
        match = re.match(pattern2, text)
        if match:
            m1, d1, m2, d2 = match.groups()
            current_year = datetime.date.today().year
            return (datetime.date(current_year, int(m1), int(d1)), datetime.date(current_year, int(m2), int(d2)))
        
        return (None, None)
    except:
        return (None, None)

@app.route('/health', methods=['GET'])
def health_check():
    return 'OK', 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    user_state = user_states.get(user_id, {})
    
    if user_state.get('waiting_for_date_range'):
        start_date, end_date = parse_date_range(text)
        
        if start_date and end_date:
            if start_date > end_date:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 開始日期不能晚於結束日期", quick_reply=create_date_range_examples_quick_reply()))
                return
            
            days = (end_date - start_date).days + 1
            if days > 7:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 免費版建議查詢 7 天以內", quick_reply=create_date_range_examples_quick_reply()))
                return
            
            user_states[user_id] = {}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🔍 查詢中，預計 {days * 3}-{days * 5} 秒..."))
            
            thread = threading.Thread(target=query_historical_async, args=(user_id, start_date, end_date))
            thread.daemon = True
            thread.start()
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 日期格式錯誤\n\n格式：2025/11/06-2025/11/06", quick_reply=create_date_range_examples_quick_reply()))
        return
    
    if text in ["今日", "今天"]:
        airlink_data = get_current_airlink_data(API_KEY, API_SECRET, STATION_ID)
        moenv_data = get_current_moenv_data(MOENV_API_TOKEN)
        all_data = {}
        if airlink_data:
            all_data.update(airlink_data)
        if moenv_data:
            all_data.update(moenv_data)
        message = format_air_quality_message(all_data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply()))
    
    elif text in ["歷史查詢", "歷史資料"]:
        user_states[user_id] = {'waiting_for_date_range': True}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📅 請輸入日期範圍\n\n格式：2025/11/06-2025/11/06\n或：11/6-11/6\n\n💡 建議 7 天以內", quick_reply=create_date_range_examples_quick_reply()))
    
    elif text in ["選單", "功能"]:
        message = "🌟 南區案空氣品質查詢系統\n\n請選擇功能：\n\n📊 今日空品\n📅 歷史查詢\n🌐 開啟系統"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply()))
    
    elif text in ["開啟查詢系統", "開啟系統"]:
        if LIFF_ID:
            message = f"🌐 完整查詢系統：\nhttps://liff.line.me/{LIFF_ID}"
        else:
            message = "⚠️ 請設定 LIFF"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply()))
    
    else:
        start_date, end_date = parse_date_range(text)
        if start_date and end_date:
            days = (end_date - start_date).days + 1
            if days > 7:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 建議 7 天以內", quick_reply=create_main_menu_quick_reply()))
                return
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🔍 查詢中..."))
            thread = threading.Thread(target=query_historical_async, args=(user_id, start_date, end_date))
            thread.daemon = True
            thread.start()
        else:
            message = "💡 使用說明\n\n• 今日\n• 歷史查詢\n• 選單"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply()))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    print(f"🚀 啟動服務 (時間戳記已修正)")
    print(f"   API Key: {API_KEY[:10] if API_KEY else '未設定'}...")
    print(f"   Station ID: {STATION_ID}")
    app.run(host='0.0.0.0', port=port, debug=False)
