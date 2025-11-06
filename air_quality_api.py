#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
南區案空氣品質監測系統 - API 模組
提供 AirLink 和環保署資料的完整整合

功能：
1. AirLink API 整合（Current + Historic）
2. 環保署開放資料 API 整合
3. 資料清理與驗證
4. 空品等級判斷（自訂標準：PM2.5 ≤ 30, PM10 ≤ 75）
5. LINE 訊息格式化
"""

import requests
import hmac
import hashlib
import time
import datetime
import os
from typing import Dict, Optional, Tuple

# ==================== AirLink API 相關函數 ====================

def generate_signature(api_key: str, api_secret: str, t: int, 
                       station_id: str, start_ts: int, end_ts: int) -> str:
    """
    生成 AirLink API 簽名（Historic API）
    
    Args:
        api_key: API Key
        api_secret: API Secret
        t: 當前時間戳記
        station_id: 測站 ID
        start_ts: 開始時間戳記
        end_ts: 結束時間戳記
    
    Returns:
        簽名字串
    """
    parts = [
        "api-key", api_key,
        "end-timestamp", str(end_ts),
        "start-timestamp", str(start_ts),
        "station-id", str(station_id),
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def generate_current_signature(api_key: str, api_secret: str, t: int, station_id: str) -> str:
    """
    生成 AirLink API 簽名（Current API）
    
    Args:
        api_key: API Key
        api_secret: API Secret
        t: 當前時間戳記
        station_id: 測站 ID
    
    Returns:
        簽名字串
    """
    parts = [
        "api-key", api_key,
        "station-id", str(station_id),
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def get_current_airlink_data(api_key: str, api_secret: str, station_id: str) -> Optional[Dict]:
    """
    取得 AirLink 即時資料（優先使用 Current API）
    
    Args:
        api_key: API Key
        api_secret: API Secret
        station_id: 測站 ID
    
    Returns:
        測站資料字典，格式：
        {
            "南區上": {
                "PM2.5": 26.7,
                "PM10": 40.1,
                "time": "11/04 18:40 (5分鐘前)"
            },
            ...
        }
    """
    try:
        # 先嘗試使用 Current Conditions API（更即時）
        t = int(time.time())
        signature = generate_current_signature(api_key, api_secret, t, station_id)
        
        url = f"https://api.weatherlink.com/v2/current/{station_id}"
        params = {
            "api-key": api_key,
            "t": t,
            "api-signature": signature
        }
        
        print(f"📡 正在呼叫 AirLink Current API...")
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # 解析資料
            result = {}
            sensors = data.get("sensors", [])
            
            # 定義站點對應（LSID 對應站點名稱）
            station_mapping = {
                652269: "南區上",
                655484: "南區下"
            }
            
            # 取得當前時間
            current_time = datetime.datetime.now()
            
            for sensor in sensors:
                lsid = sensor.get("lsid")
                sensor_data = sensor.get("data", [])
                
                if sensor_data and lsid in station_mapping:
                    latest = sensor_data[0]  # Current API 只有一筆最新資料
                    
                    station_name = station_mapping[lsid]
                    
                    # 取得資料時間戳記
                    data_ts = latest.get("ts")
                    if data_ts:
                        data_time = datetime.datetime.fromtimestamp(data_ts)
                        time_str = data_time.strftime("%m/%d %H:%M")
                        
                        # 計算資料年齡（分鐘）
                        age_minutes = int((current_time - data_time).total_seconds() / 60)
                        if age_minutes <= 5:
                            time_label = f"{time_str} (剛更新)"
                        elif age_minutes <= 30:
                            time_label = f"{time_str} ({age_minutes}分鐘前)"
                        elif age_minutes <= 60:
                            time_label = f"{time_str} ({age_minutes}分鐘前)"
                        else:
                            hours = age_minutes // 60
                            time_label = f"{time_str} ({hours}小時前)"
                    else:
                        time_label = current_time.strftime("%m/%d %H:%M")
                    
                    # 取得 PM 數值
                    pm25 = latest.get("pm_2p5") or latest.get("pm_2p5_last")
                    pm10 = latest.get("pm_10") or latest.get("pm_10_last")
                    
                    if pm25 or pm10:
                        result[station_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_label
                        }
            
            if result:
                print(f"✅ AirLink Current API 成功，取得 {len(result)} 個測站")
                return result
        
        # 如果 Current API 失敗，回退到 Historic API
        print("⚠️ Current API 失敗，使用 Historic API")
        return get_historical_airlink_data(api_key, api_secret, station_id)
            
    except Exception as e:
        print(f"❌ AirLink Current API 異常: {e}")
        # 回退到 Historic API
        return get_historical_airlink_data(api_key, api_secret, station_id)


def get_historical_airlink_data(api_key: str, api_secret: str, station_id: str) -> Optional[Dict]:
    """
    取得 AirLink 歷史資料（備用方法）
    
    Args:
        api_key: API Key
        api_secret: API Secret
        station_id: 測站 ID
    
    Returns:
        測站資料字典
    """
    try:
        # 取得最近 1 小時的資料
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(hours=1)
        
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
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
        
        print(f"📡 正在呼叫 AirLink Historic API...")
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            result = {}
            sensors = data.get("sensors", [])
            
            station_mapping = {
                652269: "南區上",
                655484: "南區下"
            }
            
            current_time = datetime.datetime.now()
            
            for sensor in sensors:
                lsid = sensor.get("lsid")
                sensor_data = sensor.get("data", [])
                
                if sensor_data and lsid in station_mapping:
                    latest = sensor_data[-1]  # 取最後一筆（最新的）
                    station_name = station_mapping[lsid]
                    
                    # 取得資料時間
                    data_time = datetime.datetime.fromtimestamp(latest["ts"])
                    age_minutes = int((current_time - data_time).total_seconds() / 60)
                    
                    if age_minutes <= 5:
                        time_label = data_time.strftime("%m/%d %H:%M") + " (剛更新)"
                    elif age_minutes <= 30:
                        time_label = data_time.strftime("%m/%d %H:%M") + f" ({age_minutes}分鐘前)"
                    elif age_minutes <= 60:
                        time_label = data_time.strftime("%m/%d %H:%M") + f" ({age_minutes}分鐘前)"
                    else:
                        hours = age_minutes // 60
                        time_label = data_time.strftime("%m/%d %H:%M") + f" ({hours}小時前)"
                    
                    # 嘗試多種欄位取得 PM 數值
                    pm25 = (latest.get("pm_2p5_avg") or 
                           latest.get("pm_2p5") or 
                           latest.get("pm_2p5_last"))
                    pm10 = (latest.get("pm_10_avg") or 
                           latest.get("pm_10") or 
                           latest.get("pm_10_last"))
                    
                    if pm25 or pm10:
                        result[station_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_label
                        }
            
            print(f"✅ AirLink Historic API 成功，取得 {len(result)} 個測站")
            return result
        else:
            print(f"❌ AirLink Historic API 錯誤: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ AirLink Historic API 異常: {e}")
        return None


# ==================== 環保署 API 相關函數 ====================

def clean_concentration(value) -> Optional[float]:
    """
    清理環保署資料中的無效值
    
    Args:
        value: 原始數值（可能包含無效標記）
    
    Returns:
        清理後的數值，無效則返回 None
    """
    if not value:
        return None
    
    value_str = str(value).strip()
    
    # 無效標記列表
    invalid_markers = ['#', '*', 'x', 'A', 'NR', 'ND', '', '-']
    
    # 檢查是否為無效標記
    if value_str in invalid_markers:
        return None
    
    # 檢查是否包含無效字元
    for marker in invalid_markers:
        if marker and marker in value_str:
            return None
    
    # 嘗試轉換為數值
    try:
        numeric_value = float(value_str)
        # 合理範圍檢查（0-1000）
        if 0 <= numeric_value <= 1000:
            return numeric_value
    except:
        pass
    
    return None


def get_current_moenv_data(api_token: str) -> Optional[Dict]:
    """
    取得環保署即時資料
    
    Args:
        api_token: 環保署 API Token
    
    Returns:
        測站資料字典
    """
    try:
        # 環保署即時空品資料 API
        url = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
        params = {
            "api_key": api_token,
            "limit": 100,
            "format": "json"
        }
        
        print(f"📡 正在呼叫環保署 API...")
        response = requests.get(url, params=params, timeout=10, verify=False)
        
        if response.status_code == 200:
            data = response.json()
            records = data.get("records", [])
            
            result = {}
            target_stations = ["仁武", "楠梓"]
            
            current_time = datetime.datetime.now()
            
            for record in records:
                site_name = record.get("sitename", "")
                
                if site_name in target_stations:
                    pm25_raw = record.get("pm2.5", "")
                    pm10_raw = record.get("pm10", "")
                    
                    # 清理數據
                    pm25 = clean_concentration(pm25_raw)
                    pm10 = clean_concentration(pm10_raw)
                    
                    # 至少要有一個有效數值
                    if pm25 is not None or pm10 is not None:
                        publish_time = record.get("publishtime", "")
                        
                        if publish_time:
                            try:
                                # 解析時間
                                dt = datetime.datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                                age_minutes = int((current_time - dt).total_seconds() / 60)
                                
                                # 計算時間標籤
                                if age_minutes <= 15:
                                    time_str = dt.strftime("%m/%d %H:%M") + " (剛更新)"
                                elif age_minutes <= 60:
                                    time_str = dt.strftime("%m/%d %H:%M") + f" ({age_minutes}分鐘前)"
                                else:
                                    hours = age_minutes // 60
                                    time_str = dt.strftime("%m/%d %H:%M") + f" ({hours}小時前)"
                            except:
                                time_str = publish_time
                        else:
                            time_str = ""
                        
                        result[site_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_str
                        }
            
            print(f"✅ 環保署 API 成功，取得 {len(result)} 個測站")
            return result
        else:
            print(f"❌ 環保署 API 錯誤: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ 環保署 API 異常: {e}")
        return None


# ==================== 空品等級判斷 ====================

def get_aqi_level(pm25_value: Optional[float]) -> Tuple[str, str]:
    """
    根據 PM2.5 判斷空品等級（使用自訂標準：30 μg/m³）
    
    Args:
        pm25_value: PM2.5 數值
    
    Returns:
        (等級文字, 顏色代碼)
    """
    if pm25_value is None:
        return "❓ 無資料", ""
    
    try:
        pm25 = float(pm25_value)
        
        # 使用自訂標準（更嚴格）
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


# ==================== 訊息格式化 ====================

def format_air_quality_message(data: Dict) -> str:
    """
    格式化空氣品質訊息為 LINE 訊息
    
    Args:
        data: 測站資料字典
    
    Returns:
        格式化的訊息字串
    """
    if not data:
        return ("❌ 無法取得資料\n\n"
                "可能原因：\n"
                "• API 服務暫時無法連線\n"
                "• 測站設備維護中\n\n"
                "請稍後再試或點擊「開啟查詢系統」\n"
                "查看歷史資料")
    
    # 取得當前時間
    current_time = datetime.datetime.now().strftime("%m/%d %H:%M")
    
    # 標題
    message = f"🕐 查詢時間: {current_time}\n\n"
    message += "📊 最新空氣品質\n"
    message += "━━━━━━━━━━━━━━━\n\n"
    
    # 定義測站順序（依照地理位置或重要性）
    station_order = ["仁武", "楠梓", "南區上", "南區下"]
    
    # 按順序顯示測站資料
    for station in station_order:
        if station in data:
            values = data[station]
            pm25 = values.get("PM2.5")
            pm10 = values.get("PM10")
            time_str = values.get("time", "")
            
            # 判斷空品等級
            level, color = get_aqi_level(pm25)
            
            message += f"📍 {station}\n"
            
            # PM2.5 - 標示是否超標（> 30）
            if pm25 is not None:
                exceed_mark = " ⚠️" if pm25 > 30 else ""
                message += f"  PM2.5: {pm25} μg/m³{exceed_mark}  {level}\n"
            else:
                message += f"  PM2.5: -- μg/m³\n"
            
            # PM10 - 標示是否超標（> 75）
            if pm10 is not None:
                exceed_mark = " ⚠️" if pm10 > 75 else ""
                message += f"  PM10:  {pm10} μg/m³{exceed_mark}\n"
            else:
                message += f"  PM10:  -- μg/m³\n"
            
            # 資料時間
            if time_str:
                message += f"  📝 資料時間: {time_str}\n"
            
            message += "\n"
    
    # 底部說明
    message += "━━━━━━━━━━━━━━━\n"
    message += "📌 法規標準（24小時平均值）\n"
    message += "• PM2.5 ≤ 30 μg/m³\n"
    message += "• PM10  ≤ 75 μg/m³\n\n"
    message += "ℹ️ 資料來源：AirLink、環保署\n"
    message += "🔄 更新頻率：5-15 分鐘\n\n"
    message += "💡 輸入「選單」查看更多功能"
    
    return message


# ==================== 測站資訊格式化 ====================

def format_station_info() -> str:
    """
    格式化測站資訊訊息
    
    Returns:
        測站資訊訊息字串
    """
    message = "📍 監測站點資訊\n"
    message += "━━━━━━━━━━━━━━━\n\n"
    
    # AirLink 測站
    message += "【AirLink 測站】\n"
    message += "🔹 南區上\n"
    message += "   • LSID: 652269\n"
    message += "   • 類型：私人測站\n\n"
    message += "🔹 南區下\n"
    message += "   • LSID: 655484\n"
    message += "   • 類型：私人測站\n\n"
    message += "📊 監測項目：PM2.5、PM10\n"
    message += "🔄 更新頻率：每 5 分鐘\n"
    message += "🌐 資料來源：WeatherLink API\n\n"
    
    # 環保署測站
    message += "【環保署測站】\n"
    message += "🔹 仁武測站\n"
    message += "   • 地點：高雄市仁武區\n"
    message += "   • 類型：國家級測站\n\n"
    message += "🔹 楠梓測站\n"
    message += "   • 地點：高雄市楠梓區\n"
    message += "   • 類型：國家級測站\n\n"
    message += "📊 監測項目：PM2.5、PM10、O3 等\n"
    message += "🔄 更新頻率：每小時\n"
    message += "🌐 資料來源：環保署開放資料\n\n"
    
    message += "━━━━━━━━━━━━━━━\n"
    message += "🎯 涵蓋範圍：高雄市南區、仁武、楠梓\n"
    message += "💡 輸入「今日」查看即時空品"
    
    return message


# ==================== 主程式測試 ====================

if __name__ == "__main__":
    """
    測試用主程式
    """
    import sys
    
    print("=" * 50)
    print("🧪 空氣品質 API 模組測試")
    print("=" * 50)
    print()
    
    # 從環境變數讀取 API 金鑰
    api_key = os.getenv('API_KEY', '')
    api_secret = os.getenv('API_SECRET', '')
    station_id = os.getenv('STATION_ID', '')
    moenv_token = os.getenv('MOENV_API_TOKEN', '')
    
    if not all([api_key, api_secret, station_id, moenv_token]):
        print("⚠️ 請設定環境變數：")
        print("   API_KEY, API_SECRET, STATION_ID, MOENV_API_TOKEN")
        print()
        print("或在程式中直接設定：")
        print("   api_key = 'your_key'")
        print("   api_secret = 'your_secret'")
        print("   station_id = 'your_station_id'")
        print("   moenv_token = 'your_token'")
        sys.exit(1)
    
    print("📡 測試 AirLink API...")
    airlink_data = get_current_airlink_data(api_key, api_secret, station_id)
    if airlink_data:
        print(f"✅ AirLink 資料: {airlink_data}")
    else:
        print("❌ AirLink 資料取得失敗")
    print()
    
    print("📡 測試環保署 API...")
    moenv_data = get_current_moenv_data(moenv_token)
    if moenv_data:
        print(f"✅ 環保署資料: {moenv_data}")
    else:
        print("❌ 環保署資料取得失敗")
    print()
    
    # 合併資料
    all_data = {}
    if airlink_data:
        all_data.update(airlink_data)
    if moenv_data:
        all_data.update(moenv_data)
    
    if all_data:
        print("📝 格式化訊息...")
        message = format_air_quality_message(all_data)
        print()
        print("=" * 50)
        print("訊息預覽：")
        print("=" * 50)
        print(message)
        print()
        print("=" * 50)
        print("✅ 測試完成！")
        print("=" * 50)
    else:
        print("❌ 無法取得任何資料")
