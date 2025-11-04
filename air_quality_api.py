import requests
import hmac
import hashlib
import time
import datetime
import os

def generate_signature(api_key, api_secret, t, station_id, start_ts, end_ts):
    """生成 AirLink API 簽名（Historic API）"""
    parts = [
        "api-key", api_key,
        "end-timestamp", str(end_ts),
        "start-timestamp", str(start_ts),
        "station-id", str(station_id),
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def generate_current_signature(api_key, api_secret, t, station_id):
    """生成 AirLink API 簽名（Current API）"""
    parts = [
        "api-key", api_key,
        "station-id", str(station_id),
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def get_current_airlink_data(api_key, api_secret, station_id):
    """取得 AirLink 即時資料"""
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
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # 解析資料
            result = {}
            sensors = data.get("sensors", [])
            
            # 定義站點對應
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
                        else:
                            time_label = time_str
                    else:
                        time_label = current_time.strftime("%m/%d %H:%M")
                    
                    pm25 = latest.get("pm_2p5") or latest.get("pm_2p5_last")
                    pm10 = latest.get("pm_10") or latest.get("pm_10_last")
                    
                    if pm25 or pm10:
                        result[station_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_label
                        }
            
            if result:
                return result
        
        # 如果 Current API 失敗，回退到 Historic API
        print("Current API 失敗，使用 Historic API")
        return get_historical_airlink_data(api_key, api_secret, station_id)
            
    except Exception as e:
        print(f"AirLink Current API 異常: {e}")
        # 回退到 Historic API
        return get_historical_airlink_data(api_key, api_secret, station_id)


def get_historical_airlink_data(api_key, api_secret, station_id):
    """取得 AirLink 歷史資料（備用方法）"""
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
                    latest = sensor_data[-1]
                    station_name = station_mapping[lsid]
                    
                    # 取得資料時間
                    data_time = datetime.datetime.fromtimestamp(latest["ts"])
                    age_minutes = int((current_time - data_time).total_seconds() / 60)
                    
                    if age_minutes <= 5:
                        time_label = data_time.strftime("%m/%d %H:%M") + " (剛更新)"
                    elif age_minutes <= 30:
                        time_label = data_time.strftime("%m/%d %H:%M") + f" ({age_minutes}分鐘前)"
                    else:
                        time_label = data_time.strftime("%m/%d %H:%M")
                    
                    pm25 = latest.get("pm_2p5_avg") or latest.get("pm_2p5") or latest.get("pm_2p5_last")
                    pm10 = latest.get("pm_10_avg") or latest.get("pm_10") or latest.get("pm_10_last")
                    
                    if pm25 or pm10:
                        result[station_name] = {
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None,
                            "time": time_label
                        }
            
            return result
        else:
            print(f"AirLink Historic API 錯誤: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"AirLink Historic API 異常: {e}")
        return None


def clean_concentration(value):
    """清理環保署資料中的無效值"""
    if not value:
        return None
    value_str = str(value).strip()
    
    # 無效標記
    invalid_markers = ['#', '*', 'x', 'A', 'NR', 'ND', '']
    if value_str in invalid_markers:
        return None
    
    # 移除無效字元
    for marker in invalid_markers:
        if marker in value_str:
            return None
    
    try:
        numeric_value = float(value_str)
        # 合理範圍檢查
        if 0 <= numeric_value <= 1000:
            return numeric_value
    except:
        pass
    
    return None


def get_current_moenv_data(api_token):
    """取得環保署即時資料"""
    try:
        # 環保署即時空品資料 API
        url = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
        params = {
            "api_key": api_token,
            "limit": 100,
            "format": "json"
        }
        
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
                    
                    pm25 = clean_concentration(pm25_raw)
                    pm10 = clean_concentration(pm10_raw)
                    
                    if pm25 is not None or pm10 is not None:
                        publish_time = record.get("publishtime", "")
                        if publish_time:
                            try:
                                dt = datetime.datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                                age_minutes = int((current_time - dt).total_seconds() / 60)
                                
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
            
            return result
        else:
            print(f"環保署 API 錯誤: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"環保署 API 異常: {e}")
        return None


def get_aqi_level(pm25_value):
    """根據 PM2.5 判斷空品等級"""
    if pm25_value is None:
        return "❓ 無資料", ""
    
    try:
        pm25 = float(pm25_value)
        if pm25 <= 15:
            return "😊 良好", "#00E400"
        elif pm25 <= 25:
            return "🙂 普通", "#FFFF00"
        elif pm25 <= 30:
            return "😐 對敏感族群不健康", "#FF7E00"
        elif pm25 <= 40:
            return "😷 對所有族群不健康", "#FF0000"
        elif pm25 <= 50:
            return "😨 非常不健康", "#8F3F97"
        else:
            return "☠️ 危害", "#7E0023"
    except:
        return "❓ 無資料", ""


def format_air_quality_message(data):
    """格式化空氣品質訊息為 LINE 訊息"""
    if not data:
        return "❌ 無法取得資料\n\n可能原因：\n• API 服務暫時無法連線\n• 測站設備維護中\n\n請稍後再試或點擊「開啟查詢系統」\n查看歷史資料"
    
    # 取得當前時間
    current_time = datetime.datetime.now().strftime("%m/%d %H:%M")
    
    # 標題
    message = f"🕐 查詢時間: {current_time}\n\n"
    message += "📊 最新空氣品質\n"
    message += "━━━━━━━━━━━━━━━\n\n"
    
    # 定義測站順序
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
            
            # PM2.5
            if pm25 is not None:
                message += f"  PM2.5: {pm25} μg/m³  {level}\n"
            else:
                message += f"  PM2.5: -- μg/m³\n"
            
            # PM10
            if pm10 is not None:
                message += f"  PM10:  {pm10} μg/m³\n"
            else:
                message += f"  PM10:  -- μg/m³\n"
            
            # 資料時間
            if time_str:
                message += f"  📝 資料時間: {time_str}\n"
            
            message += "\n"
    
    # 底部說明
    message += "━━━━━━━━━━━━━━━\n"
    message += "📌 空氣品質標準（24小時平均值）\n"
    message += "• PM2.5 良好 ≤ 15 μg/m³\n"
    message += "• PM2.5 普通 ≤ 25 μg/m³\n"
    message += "• PM10  良好 ≤ 54 μg/m³\n"
    message += "• PM10  普通 ≤ 125 μg/m³\n\n"
    message += "ℹ️ 資料來源：AirLink、環保署\n"
    message += "🔄 每 5-15 分鐘更新\n\n"
    message += "💡 輸入「選單」查看更多功能"
    
    return message
