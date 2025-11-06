#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
air_quality_api.py - 時區修正版 (台灣時間 UTC+8)
功能：
- 從 WeatherLink 抓取 AirLink 即時資料（LSID: 652269、655484）
- 從環保署 API 抓取官方測站資料（仁武、楠梓）
- 自動修正時間為台灣時區，顯示正確時間戳記
"""

import requests
import hmac
import hashlib
import time
import datetime
import os
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

# === AirLink 測站設定 ===
AIRLINK_LSIDS = {
    652269: "南區上",
    655484: "南區下"
}

# 台灣時區
TW_TZ = ZoneInfo("Asia/Taipei")

# === WeatherLink 簽名產生 ===
def generate_current_signature(api_key: str, api_secret: str, t: int, station_id: str) -> str:
    parts = ["api-key", api_key, "station-id", str(station_id), "t", str(t)]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()

# === AirLink 即時資料 ===
def get_current_airlink_data(api_key: str, api_secret: str, station_id: str) -> Optional[Dict]:
    """取得 AirLink 即時資料（台灣時間）"""
    try:
        if not station_id:
            station_id = "167944"

        t = int(time.time())
        signature = generate_current_signature(api_key, api_secret, t, station_id)
        url = f"https://api.weatherlink.com/v2/current/{station_id}"
        params = {"api-key": api_key, "t": t, "api-signature": signature}

        print(f"📡 AirLink API: {datetime.datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ AirLink API 狀態碼: {response.status_code}")
            return None

        data = response.json()
        result = {}
        sensors = data.get("sensors", [])
        current_time = datetime.datetime.now(TW_TZ)

        print(f"   找到 {len(sensors)} 個感測器")

        for sensor in sensors:
            lsid = sensor.get("lsid")
            if lsid not in AIRLINK_LSIDS:
                continue

            station_name = AIRLINK_LSIDS[lsid]
            sensor_data = sensor.get("data", [])

            if not sensor_data:
                continue

            latest = sensor_data[0]

            # 優先使用 _last 欄位
            pm25 = latest.get("pm_2p5_last") or latest.get("pm_2p5")
            pm10 = latest.get("pm_10_last") or latest.get("pm_10")

            # 時間修正：UTC → 台灣時間
            data_ts = latest.get("ts")
            if data_ts:
                data_time = datetime.datetime.fromtimestamp(data_ts, tz=TW_TZ)
                time_label = data_time.strftime("%Y/%m/%d %H:%M")  # ✅ 修正：定義時間字串
                age_minutes = int((current_time - data_time).total_seconds() / 60)
            else:
                time_label = current_time.strftime("%Y/%m/%d %H:%M")
                age_minutes = None

            if pm25 is not None or pm10 is not None:
                result[station_name] = {
                    "PM2.5": round(pm25, 1) if pm25 else None,
                    "PM10": round(pm10, 1) if pm10 else None,
                    "time": time_label
                }
                print(f"   ✅ {station_name}: PM2.5={pm25}, PM10={pm10}, 年齡={age_minutes if age_minutes else '?'}分")

        if result:
            print(f"✅ AirLink 成功抓取 {len(result)} 個測站")
            return result
        else:
            print("⚠️ 無符合 LSID 的 AirLink 測站資料")
            return None

    except Exception as e:
        print(f"❌ AirLink 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return None

# === 環保署 API 處理 ===
def clean_concentration(value) -> Optional[float]:
    """清理濃度數據"""
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

def get_current_moenv_data(api_token: str) -> Optional[Dict]:
    """取得環保署即時空氣品質資料"""
    try:
        url = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
        params = {"api_key": api_token, "limit": 100, "format": "json"}
        print("📡 環保署 API...")
        response = requests.get(url, params=params, timeout=10, verify=False)

        if response.status_code != 200:
            print(f"⚠️ 環保署 API 狀態碼: {response.status_code}")
            return None

        data = response.json()
        records = data.get("records", [])
        result = {}
        target_stations = ["仁武", "楠梓"]
        current_time = datetime.datetime.now(TW_TZ)

        for record in records:
            site_name = record.get("sitename", "")
            if site_name not in target_stations:
                continue

            pm25 = clean_concentration(record.get("pm2.5", ""))
            pm10 = clean_concentration(record.get("pm10", ""))
            publish_time = record.get("publishtime", "")

            if publish_time:
                try:
                    dt = datetime.datetime.strptime(publish_time, "%Y-%m-%d %H:%M")
                    dt = dt.replace(tzinfo=TW_TZ)
                    time_str = dt.strftime("%Y/%m/%d %H:%M")  # ✅ 修正：定義時間字串
                except:
                    time_str = publish_time
            else:
                time_str = ""

            if pm25 is not None or pm10 is not None:
                result[site_name] = {
                    "PM2.5": round(pm25, 1) if pm25 else None,
                    "PM10": round(pm10, 1) if pm10 else None,
                    "time": time_str
                }

        print(f"✅ 環保署成功抓取 {len(result)} 個測站")
        return result if result else None

    except Exception as e:
        print(f"❌ 環保署錯誤: {e}")
        return None

# === 空氣品質等級判定 ===
def get_aqi_level(pm25_value: Optional[float]) -> Tuple[str, str]:
    """判斷空品等級"""
    if pm25_value is None:
        return "❓ 無資料", ""
    try:
        pm25 = float(pm25_value)
        if pm25 <= 10:
            return "😊 優良", "#00E400"
        elif pm25 <= 20:
            return "🙂 良好", "#FFFF00"
        elif pm25 <= 30:
            return "😐 普通", "#FF7E00"
        elif pm25 <= 50:
            return "😷 不良", "#FF0000"
        else:
            return "☠️ 非常不良", "#7E0023"
    except:
        return "❓ 無資料", ""

# === 格式化輸出 ===
def format_air_quality_message(data: Dict) -> str:
    """格式化顯示文字"""
    if not data:
        return "❌ 無法取得資料\n\n請稍後再試或點擊「開啟查詢系統」"

    current_time = datetime.datetime.now(TW_TZ).strftime("%m/%d %H:%M")
    message = f"🕐 查詢時間: {current_time}\n\n📊 最新空氣品質\n━━━━━━━━━━━━━━━\n\n"

    station_order = ["仁武", "楠梓", "南區上", "南區下"]

    for station in station_order:
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

    message += "━━━━━━━━━━━━━━━\n📌 法規標準（24小時平均值）\n• PM2.5 ≤ 30 μg/m³\n• PM10  ≤ 75 μg/m³\n\n"
    message += "ℹ️ 資料來源：AirLink、環保署\n🔄 更新頻率：5-15 分鐘\n\n💡 輸入「選單」查看更多功能"
    return message

# === 測站說明 ===
def format_station_info() -> str:
    return """📍 監測站點資訊
━━━━━━━━━━━━━━━

【AirLink 測站】
🔹 南區上
   • LSID: 652269
   • 類型：私人測站

🔹 南區下
   • LSID: 655484
   • 類型：私人測站

📊 監測項目：PM2.5、PM10
🔄 更新頻率：每 5 分鐘
🌐 資料來源：WeatherLink API

【環保署測站】
🔹 仁武測站
   • 地點：高雄市仁武區
   • 類型：國家級測站

🔹 楠梓測站
   • 地點：高雄市楠梓區
   • 類型：國家級測站

📊 監測項目：PM2.5、PM10、O3 等
🔄 更新頻率：每小時
🌐 資料來源：環保署開放資料

━━━━━━━━━━━━━━━
🎯 涵蓋範圍：高雄市南區、仁武、楠梓
💡 輸入「今日」查看即時空品"""

# === 主程式 ===
if __name__ == "__main__":
    import sys
    print("🧪 API 測試（時區修正版）")

    api_key = os.getenv('API_KEY', '')
    api_secret = os.getenv('API_SECRET', '')
    station_id = os.getenv('STATION_ID', '')
    moenv_token = os.getenv('MOENV_API_TOKEN', '')

    if not all([api_key, api_secret]):
        print("⚠️ 請設定 API_KEY、API_SECRET 環境變數 (.env)")
        sys.exit(1)

    print(f"\nStation ID: {station_id or '167944'}")
    print(f"目標 LSID: {list(AI
