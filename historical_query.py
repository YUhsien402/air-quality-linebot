#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
historical_query.py - 歷史資料查詢模組
提供日期範圍查詢、統計摘要、趨勢圖等功能
"""

import requests
import hmac
import hashlib
import time
import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import pandas as pd

# 台灣時區
TW_TZ = ZoneInfo("Asia/Taipei")

# LSID 對應
AIRLINK_LSIDS = {
    652269: "南區上",
    655484: "南區下"
}

def generate_signature(api_key: str, api_secret: str, t: int, station_id: str, start_ts: int, end_ts: int) -> str:
    """生成 Historic API 簽名"""
    parts = [
        "api-key", api_key,
        "end-timestamp", str(end_ts),
        "start-timestamp", str(start_ts),
        "station-id", str(station_id),
        "t", str(t)
    ]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()

def fetch_airlink_historical(api_key: str, api_secret: str, station_id: str, start_ts: int, end_ts: int) -> Optional[Dict]:
    """取得 AirLink 歷史資料"""
    try:
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
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Historic API 錯誤: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Historic API 異常: {e}")
        return None

def fetch_airlink_data_range(api_key: str, api_secret: str, station_id: str, start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
    """
    取得指定日期範圍的 AirLink 資料
    
    Args:
        api_key: API Key
        api_secret: API Secret
        station_id: Station ID
        start_date: 開始日期
        end_date: 結束日期
    
    Returns:
        List of records with device, date, datetime, PM2.5, PM10
    """
    all_records = []
    
    start_dt = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=TW_TZ)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max, tzinfo=TW_TZ)
    
    current_dt = start_dt
    
    print(f"📡 查詢 AirLink 資料: {start_date} ~ {end_date}")
    
    # 逐日查詢（避免單次查詢太多資料）
    while current_dt <= end_dt:
        next_dt = min(current_dt + datetime.timedelta(days=1), end_dt)
        
        start_ts = int(current_dt.timestamp())
        end_ts = int(next_dt.timestamp())
        
        data = fetch_airlink_historical(api_key, api_secret, station_id, start_ts, end_ts)
        
        if data:
            sensors = data.get("sensors", [])
            
            for sensor in sensors:
                lsid = sensor.get("lsid")
                
                if lsid in AIRLINK_LSIDS:
                    station_name = AIRLINK_LSIDS[lsid]
                    sensor_data = sensor.get("data", [])
                    
                    for record in sensor_data:
                        ts = record.get("ts")
                        if ts:
                            # 轉換為台灣時間
                            timestamp = datetime.datetime.fromtimestamp(ts, tz=TW_TZ)
                            date_str = timestamp.strftime("%Y/%m/%d")
                            datetime_str = timestamp.strftime("%Y/%m/%d %H:%M")
                            
                            # 取得 PM 值
                            pm25 = record.get("pm_2p5_avg") or record.get("pm_2p5") or record.get("pm_2p5_last")
                            pm10 = record.get("pm_10_avg") or record.get("pm_10") or record.get("pm_10_last")
                            
                            if pm25 is not None or pm10 is not None:
                                all_records.append({
                                    "device": station_name,
                                    "date": date_str,
                                    "datetime": datetime_str,
                                    "PM2.5": round(pm25, 1) if pm25 else None,
                                    "PM10": round(pm10, 1) if pm10 else None
                                })
        
        current_dt = next_dt
        time.sleep(1)  # 避免 API 限速
    
    print(f"✅ 取得 {len(all_records)} 筆 AirLink 資料")
    return all_records

def clean_concentration(value) -> Optional[float]:
    """清理環保署資料"""
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

def fetch_moenv_data_range(api_token: str, start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
    """
    取得指定日期範圍的環保署資料
    """
    moenv_records = []
    moenv_stations = {"AQX_P_237": "仁武", "AQX_P_241": "楠梓"}
    
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    print(f"📡 查詢環保署資料: {start_date} ~ {end_date}")
    
    for dataset_id, station_name in moenv_stations.items():
        offset = 0
        limit = 1000
        date_filter = f"monitordate,GR,{start_date_str} 00:00:00|monitordate,LE,{end_date_str} 23:59:59|itemid,EQ,33,4"
        
        while True:
            url = f"https://data.moenv.gov.tw/api/v2/{dataset_id}"
            params = {
                "api_key": api_token,
                "format": "json",
                "offset": offset,
                "limit": limit,
                "filters": date_filter
            }
            
            try:
                response = requests.get(url, params=params, timeout=30, verify=False)
                response.raise_for_status()
                data = response.json()
                records = data.get("records", [])
                
                if not records:
                    break
                
                for record in records:
                    record['station_name'] = station_name
                
                moenv_records.extend(records)
                
                if len(records) < limit:
                    break
                
                offset += limit
                time.sleep(0.5)
                
            except Exception as e:
                print(f"❌ 環保署 API 錯誤: {e}")
                break
    
    print(f"✅ 取得 {len(moenv_records)} 筆環保署資料")
    return moenv_records

def calculate_daily_averages(airlink_records: List[Dict], moenv_records: List[Dict]) -> pd.DataFrame:
    """
    計算每日平均值
    
    Returns:
        DataFrame with columns: device, date, PM2.5, PM10
    """
    # 處理 AirLink 資料
    airlink_df = pd.DataFrame(airlink_records)
    if not airlink_df.empty:
        airlink_daily = airlink_df.groupby(["device", "date"]).agg({
            "PM2.5": "mean",
            "PM10": "mean"
        }).reset_index()
        airlink_daily["PM2.5"] = airlink_daily["PM2.5"].round(0).astype(int)
        airlink_daily["PM10"] = airlink_daily["PM10"].round(0).astype(int)
    else:
        airlink_daily = pd.DataFrame()
    
    # 處理環保署資料
    moenv_df = pd.DataFrame(moenv_records)
    if not moenv_df.empty:
        moenv_df['concentration'] = moenv_df['concentration'].apply(clean_concentration)
        moenv_df = moenv_df[moenv_df['concentration'].notna()].copy()
        moenv_df['concentration'] = pd.to_numeric(moenv_df['concentration'], errors='coerce')
        moenv_df['itemid'] = moenv_df['itemid'].astype(str)
        moenv_df['date'] = pd.to_datetime(moenv_df['monitordate']).dt.date
        moenv_df['date'] = moenv_df['date'].astype(str).str.replace('-', '/')
        moenv_df = moenv_df[moenv_df['itemid'].isin(['33', '4'])].copy()
        moenv_df['pollutant'] = moenv_df['itemid'].map({'33': 'PM2.5', '4': 'PM10'})
        
        moenv_daily = moenv_df.groupby(['station_name', 'date', 'pollutant']).agg({
            'concentration': 'mean'
        }).reset_index()
        
        moenv_daily_wide = moenv_daily.pivot_table(
            index=['station_name', 'date'],
            columns='pollutant',
            values='concentration'
        ).reset_index()
        
        moenv_daily_wide['PM2.5'] = moenv_daily_wide['PM2.5'].round(0).astype(int)
        moenv_daily_wide['PM10'] = moenv_daily_wide['PM10'].round(0).astype(int)
        moenv_daily_wide.rename(columns={'station_name': 'device'}, inplace=True)
    else:
        moenv_daily_wide = pd.DataFrame()
    
    # 合併資料
    if not airlink_daily.empty and not moenv_daily_wide.empty:
        all_daily = pd.concat([airlink_daily, moenv_daily_wide], ignore_index=True)
    elif not airlink_daily.empty:
        all_daily = airlink_daily
    elif not moenv_daily_wide.empty:
        all_daily = moenv_daily_wide
    else:
        all_daily = pd.DataFrame()
    
    return all_daily

def format_daily_table_message(all_daily: pd.DataFrame, start_date: datetime.date, end_date: datetime.date) -> str:
    """
    格式化每日平均值表格訊息
    """
    if all_daily.empty:
        return "❌ 查詢期間無資料"
    
    station_order = ["仁武", "楠梓", "南區上", "南區下"]
    available_stations = [s for s in station_order if s in all_daily['device'].unique()]
    
    # 建立 pivot table
    pivot_pm25 = all_daily.pivot(index='date', columns='device', values='PM2.5')
    pivot_pm10 = all_daily.pivot(index='date', columns='device', values='PM10')
    
    pivot_pm25 = pivot_pm25[[s for s in available_stations if s in pivot_pm25.columns]]
    pivot_pm10 = pivot_pm10[[s for s in available_stations if s in pivot_pm10.columns]]
    
    # 轉換為民國年
    dates_roc = []
    for date_str in pivot_pm25.index:
        parts = date_str.split('/')
        year_roc = int(parts[0]) - 1911
        month = int(parts[1])
        day = int(parts[2])
        dates_roc.append(f"{year_roc}/{month}/{day}")
    
    # 格式化訊息
    message = f"📅 查詢期間: {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')}\n\n"
    message += "📊 每日平均值\n"
    message += "━━━━━━━━━━━━━━━\n\n"
    
    # 表頭
    header = "日期".ljust(10)
    for station in available_stations:
        header += f"{station}".ljust(12)
    message += header + "\n"
    message += "     " + " PM2.5 PM10  " * len(available_stations) + "\n"
    message += "─" * (10 + 12 * len(available_stations)) + "\n"
    
    # 資料行
    for i, date_roc in enumerate(dates_roc):
        row = date_roc.ljust(10)
        
        for station in available_stations:
            pm25 = pivot_pm25.loc[pivot_pm25.index[i], station] if station in pivot_pm25.columns else None
            pm10 = pivot_pm10.loc[pivot_pm10.index[i], station] if station in pivot_pm10.columns else None
            
            pm25_str = str(int(pm25)).rjust(3) if pd.notna(pm25) else " --"
            pm10_str = str(int(pm10)).rjust(3) if pd.notna(pm10) else " --"
            
            row += f" {pm25_str}  {pm10_str} "
        
        message += row + "\n"
    
    return message

def format_statistics_message(all_daily: pd.DataFrame) -> str:
    """
    格式化統計摘要訊息
    """
    if all_daily.empty:
        return ""
    
    station_order = ["仁武", "楠梓", "南區上", "南區下"]
    available_stations = [s for s in station_order if s in all_daily['device'].unique()]
    
    message = "\n━━━━━━━━━━━━━━━\n"
    message += "📊 統計摘要\n"
    message += "━━━━━━━━━━━━━━━\n\n"
    
    # PM2.5 統計
    message += "【PM2.5】(法規標準: 30μg/m³)\n"
    message += "測站    最小  最大\n"
    message += "─" * 20 + "\n"
    
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            min_val = int(station_data['PM2.5'].min())
            max_val = int(station_data['PM2.5'].max())
            message += f"{station.ljust(6)} {str(min_val).rjust(3)}  {str(max_val).rjust(3)}\n"
    
    message += "\n"
    
    # PM10 統計
    message += "【PM10】(法規標準: 75μg/m³)\n"
    message += "測站    最小  最大\n"
    message += "─" * 20 + "\n"
    
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            min_val = int(station_data['PM10'].min())
            max_val = int(station_data['PM10'].max())
            message += f"{station.ljust(6)} {str(min_val).rjust(3)}  {str(max_val).rjust(3)}\n"
    
    message += "\n━━━━━━━━━━━━━━━\n"
    message += "ℹ️ 資料來源：AirLink、環保署"
    
    return message

def query_historical_data(api_key: str, api_secret: str, station_id: str, 
                         moenv_token: str, start_date: datetime.date, 
                         end_date: datetime.date) -> str:
    """
    查詢歷史資料並返回格式化訊息
    
    Args:
        api_key: AirLink API Key
        api_secret: AirLink API Secret
        station_id: AirLink Station ID
        moenv_token: 環保署 API Token
        start_date: 開始日期
        end_date: 結束日期
    
    Returns:
        格式化的查詢結果訊息
    """
    try:
        # 日期驗證
        if start_date > end_date:
            return "❌ 開始日期不能晚於結束日期"
        
        if (end_date - start_date).days > 30:
            return "❌ 查詢範圍不能超過 30 天"
        
        # 取得資料
        airlink_records = fetch_airlink_data_range(api_key, api_secret, station_id, start_date, end_date)
        moenv_records = fetch_moenv_data_range(moenv_token, start_date, end_date)
        
        # 計算每日平均
        all_daily = calculate_daily_averages(airlink_records, moenv_records)
        
        if all_daily.empty:
            return f"❌ {start_date.strftime('%Y/%m/%d')} ~ {end_date.strftime('%Y/%m/%d')} 期間無資料"
        
        # 格式化訊息
        table_message = format_daily_table_message(all_daily, start_date, end_date)
        stats_message = format_statistics_message(all_daily)
        
        return table_message + stats_message
        
    except Exception as e:
        print(f"❌ 查詢失敗: {e}")
        import traceback
        traceback.print_exc()
        return f"❌ 查詢失敗: {str(e)}"

# 測試
if __name__ == "__main__":
    import os
    
    api_key = os.getenv('API_KEY', '')
    api_secret = os.getenv('API_SECRET', '')
    station_id = os.getenv('STATION_ID', '')
    moenv_token = os.getenv('MOENV_API_TOKEN', '')
    
    if all([api_key, api_secret, station_id, moenv_token]):
        start_date = datetime.date(2025, 10, 1)
        end_date = datetime.date(2025, 10, 7)
        
        print("🧪 測試歷史查詢功能")
        print(f"查詢範圍: {start_date} ~ {end_date}")
        print()
        
        result = query_historical_data(api_key, api_secret, station_id, moenv_token, start_date, end_date)
        print(result)
    else:
        print("⚠️ 請設定環境變數")
