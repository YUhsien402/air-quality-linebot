import streamlit as st
import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import datetime
import urllib3
import plotly.graph_objects as go
from PIL import Image

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 讀取圖片
logo = Image.open("圖片1.png")

st.set_page_config(
    page_title="南區案空氣品質查詢系統",
    page_icon=logo,
    layout="wide"
)

try:
    AIRLINK_API_KEY = st.secrets["API_KEY"]
    AIRLINK_API_SECRET = st.secrets["API_SECRET"]
    AIRLINK_STATION_ID = st.secrets["STATION_ID"]
    MOENV_API_TOKEN = st.secrets["MOENV_API_TOKEN"]
except:
    AIRLINK_API_KEY = os.getenv("API_KEY", "")
    AIRLINK_API_SECRET = os.getenv("API_SECRET", "")
    AIRLINK_STATION_ID = os.getenv("STATION_ID", "")
    MOENV_API_TOKEN = os.getenv("MOENV_API_TOKEN", "")

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)


def generate_signature(api_key, api_secret, t, station_id, start_ts, end_ts):
    parts = ["api-key", api_key, "end-timestamp", str(end_ts), "start-timestamp", str(start_ts), "station-id",
             str(station_id), "t", str(t)]
    data = "".join(parts)
    return hmac.new(api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def fetch_airlink_historical(api_key, api_secret, station_id, start_ts, end_ts):
    t = int(time.time())
    signature = generate_signature(api_key, api_secret, t, station_id, start_ts, end_ts)
    url = "https://api.weatherlink.com/v2/historic/" + str(station_id)
    params = {"api-key": api_key, "t": t, "start-timestamp": start_ts, "end-timestamp": end_ts,
              "api-signature": signature}
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        st.error("AirLink API 錯誤: " + str(e))
        return None


def fetch_airlink_data(api_key, api_secret, station_id, lsids_dict, start_dt, end_dt_fetch, progress_bar):
    all_records = []
    current_dt = start_dt
    total_days = (end_dt_fetch - start_dt).days
    if total_days <= 0:
        total_days = 1
    day_count = 0

    while current_dt < end_dt_fetch:
        next_dt = min(current_dt + datetime.timedelta(days=1), end_dt_fetch)
        start_ts = int(current_dt.timestamp())
        end_ts = int(next_dt.timestamp())
        data = fetch_airlink_historical(api_key, api_secret, station_id, start_ts, end_ts)

        if data:
            sensors = data.get("sensors", [])
            for sensor in sensors:
                lsid = sensor.get("lsid")
                if lsid not in lsids_dict:
                    continue
                device_name = lsids_dict[lsid]
                sensor_data = sensor.get("data", [])
                for record in sensor_data:
                    timestamp = datetime.datetime.fromtimestamp(record["ts"])
                    date_str = timestamp.strftime("%Y/%m/%d")
                    datetime_str = timestamp.strftime("%Y/%m/%d %H:%M")
                    pm25 = record.get("pm_2p5_avg") or record.get("pm_2p5") or record.get("pm_2p5_last")
                    pm10 = record.get("pm_10_avg") or record.get("pm_10") or record.get("pm_10_last")
                    if pm25 is not None or pm10 is not None:
                        all_records.append({
                            "device": device_name,
                            "date": date_str,
                            "datetime": datetime_str,
                            "PM2.5": round(pm25, 1) if pm25 else None,
                            "PM10": round(pm10, 1) if pm10 else None
                        })

        current_dt = next_dt
        day_count += 1
        if progress_bar:
            progress_value = min(day_count / total_days, 1.0)
            progress_bar.progress(progress_value)
        time.sleep(1)
    return all_records


def clean_concentration(value):
    if pd.isna(value):
        return None
    value_str = str(value).strip()
    invalid_markers = ['#', '*', 'x', 'A', 'NR']
    if value_str in invalid_markers or value_str == '':
        return None
    for marker in invalid_markers:
        if marker in value_str:
            return None
    try:
        numeric_value = float(value_str)
        if 0 <= numeric_value <= 1000:
            return numeric_value
    except:
        pass
    return None


def fetch_moenv_station(dataset_id, api_token, start_date, end_date):
    api_url = "https://data.moenv.gov.tw/api/v2"
    all_records = []
    offset = 0
    limit = 1000
    date_filter = "monitordate,GR," + start_date + " 00:00:00|monitordate,LE," + end_date + " 23:59:59|itemid,EQ,33,4"

    while True:
        url = api_url + "/" + dataset_id
        params = {"api_key": api_token, "format": "json", "offset": offset, "limit": limit, "filters": date_filter}
        try:
            response = requests.get(url, params=params, timeout=30, verify=False)
            response.raise_for_status()
            data = response.json()
            records = data.get("records", [])
            if not records:
                break
            all_records.extend(records)
            if len(records) < limit:
                break
            offset += limit
            time.sleep(0.5)
        except Exception as e:
            st.error("環保署 API 錯誤: " + str(e))
            break
    return all_records


# 初始化 session state
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'all_daily' not in st.session_state:
    st.session_state.all_daily = None
if 'airlink_records' not in st.session_state:
    st.session_state.airlink_records = None
if 'moenv_records' not in st.session_state:
    st.session_state.moenv_records = None
if 'result_df' not in st.session_state:
    st.session_state.result_df = None
if 'available_stations' not in st.session_state:
    st.session_state.available_stations = None
if 'start_dt' not in st.session_state:
    st.session_state.start_dt = None
if 'end_dt' not in st.session_state:
    st.session_state.end_dt = None
if 'pivot_pm25' not in st.session_state:
    st.session_state.pivot_pm25 = None
if 'pivot_pm10' not in st.session_state:
    st.session_state.pivot_pm10 = None

# 顯示 Logo 和標題
st.markdown("""
<style>
.logo-title-container {
    text-align: center;
    margin-bottom: 2rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
}
.logo-title-container img {
    width: clamp(100px, 20vw, 150px);
    height: auto;
    display: block;
    margin: 0 auto;
}
.main-title {
  text-align: center;
  font-size: clamp(1.2rem, 3.5vw, 2rem);
  font-weight: bold;
  color: #0088cc;
  margin-top: -85px;
  margin-left: 50px; 
  line-height: 1.3;
  padding: 0 1rem;
  word-wrap: break-word;
}
}
/* 手機版調整 */
@media (max-width: 768px) {
    .main-title {
        font-size: 1.3rem;
    }

    .logo-title-container img {
        width: 100px;
    }

    .logo-title-container {
        gap: 0.3rem;
    }
}
/* 平板版調整 */
@media (min-width: 769px) and (max-width: 1024px) {
    .main-title {
        font-size: 1.6rem;
    }
}
</style>
""", unsafe_allow_html=True)

# 使用單一容器來確保元素不會分離
st.markdown('<div class="logo-title-container">', unsafe_allow_html=True)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.image("圖片1.png", width=100)
st.markdown('''
<div class="main-title">
南區案空氣品質查詢系統
</div>
</div>
''', unsafe_allow_html=True)

with st.sidebar:
    st.header("📅 查詢設定")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("起始日期", value=datetime.date(2025, 10, 1))
    with col2:
        end_date = st.date_input("結束日期", value=datetime.date(2025, 10, 7))
    st.divider()
    st.subheader("🎯 測站資訊")
    st.markdown("- **AirLink**: 南區上、南區下\n- **環保署**: 仁武、楠梓")
    st.divider()
    query_button = st.button("🔍 開始查詢", use_container_width=True, type="primary")
    st.divider()
    st.caption("系統狀態")
    if AIRLINK_API_KEY and AIRLINK_API_SECRET and AIRLINK_STATION_ID:
        st.success("✅ AirLink 已設定")
    else:
        st.warning("⚠️ AirLink 未設定")
    if MOENV_API_TOKEN:
        st.success("✅ 環保署 已設定")
    else:
        st.warning("⚠️ 環保署 未設定")

if query_button:
    if not all([AIRLINK_API_KEY, AIRLINK_API_SECRET, AIRLINK_STATION_ID, MOENV_API_TOKEN]):
        st.error("⚠️ 系統未正確設定，請聯絡管理員")
        st.stop()

    AIRLINK_LSIDS = {652269: "南區上", 655484: "南區下"}
    MOENV_STATIONS = {"AQX_P_237": "仁武", "AQX_P_241": "楠梓"}
    STATION_ORDER = ["仁武", "楠梓", "南區上", "南區下"]

    # 跟原始版本一致的日期處理
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.min)
    end_dt_fetch = end_dt + datetime.timedelta(days=1)

    try:
        st.subheader("🌐 AirLink 資料")
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text("正在抓取 AirLink 資料...")

        airlink_records = fetch_airlink_data(AIRLINK_API_KEY, AIRLINK_API_SECRET, AIRLINK_STATION_ID, AIRLINK_LSIDS,
                                             start_dt, end_dt_fetch, progress_bar)
        status_text.success("✅ 抓取 " + str(len(airlink_records)) + " 筆 AirLink 資料")

        st.subheader("🏛️ 環保署資料")
        status_text2 = st.empty()
        status_text2.text("正在抓取環保署資料...")
        moenv_records = []
        moenv_start = start_dt.strftime("%Y-%m-%d")
        moenv_end = end_dt.strftime("%Y-%m-%d")
        for dataset_id, station_name in MOENV_STATIONS.items():
            records = fetch_moenv_station(dataset_id, MOENV_API_TOKEN, moenv_start, moenv_end)
            for record in records:
                record['station_name'] = station_name
            moenv_records.extend(records)
        status_text2.success("✅ 抓取 " + str(len(moenv_records)) + " 筆環保署資料")

        st.subheader("📋 資料整理")
        airlink_df = pd.DataFrame(airlink_records)
        if not airlink_df.empty:
            airlink_daily = airlink_df.groupby(["device", "date"]).agg({"PM2.5": "mean", "PM10": "mean"}).reset_index()
            airlink_daily["PM2.5"] = airlink_daily["PM2.5"].round(0).astype(int)
            airlink_daily["PM10"] = airlink_daily["PM10"].round(0).astype(int)
        else:
            airlink_daily = pd.DataFrame()

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
            moenv_daily = moenv_df.groupby(['station_name', 'date', 'pollutant']).agg(
                {'concentration': 'mean'}).reset_index()
            moenv_daily_wide = moenv_daily.pivot_table(index=['station_name', 'date'], columns='pollutant',
                                                       values='concentration').reset_index()
            moenv_daily_wide['PM2.5'] = moenv_daily_wide['PM2.5'].round(0).astype(int)
            moenv_daily_wide['PM10'] = moenv_daily_wide['PM10'].round(0).astype(int)
            moenv_daily_wide.rename(columns={'station_name': 'device'}, inplace=True)
        else:
            moenv_daily_wide = pd.DataFrame()

        if not airlink_daily.empty and not moenv_daily_wide.empty:
            all_daily = pd.concat([airlink_daily, moenv_daily_wide], ignore_index=True)
        elif not airlink_daily.empty:
            all_daily = airlink_daily
        elif not moenv_daily_wide.empty:
            all_daily = moenv_daily_wide
        else:
            st.error("❌ 沒有任何資料")
            st.stop()

        # 過濾日期範圍（只保留 start_date 到 end_date）
        start_date_str = start_dt.strftime("%Y/%m/%d")
        end_date_str = end_dt.strftime("%Y/%m/%d")
        all_daily = all_daily[(all_daily['date'] >= start_date_str) & (all_daily['date'] <= end_date_str)].copy()

        available_stations = [s for s in STATION_ORDER if s in all_daily['device'].unique()]
        pivot_pm25 = all_daily.pivot(index='date', columns='device', values='PM2.5')
        pivot_pm10 = all_daily.pivot(index='date', columns='device', values='PM10')

        pivot_pm25 = pivot_pm25[[s for s in available_stations if s in pivot_pm25.columns]]
        pivot_pm10 = pivot_pm10[[s for s in available_stations if s in pivot_pm10.columns]]

        result_df = pd.DataFrame()

        # 轉換日期為民國年格式
        dates_roc = []
        for date_str in pivot_pm25.index:
            parts = date_str.split('/')
            year_roc = int(parts[0]) - 1911
            month = int(parts[1])
            day = int(parts[2])
            dates_roc.append(str(year_roc) + "/" + str(month) + "/" + str(day))

        result_df['日期'] = dates_roc

        for station in available_stations:
            if station in pivot_pm25.columns:
                result_df[station + '_PM2.5'] = pivot_pm25[station].values
                result_df[station + '_PM10'] = pivot_pm10[station].values

        # 儲存到 session state
        st.session_state.data_loaded = True
        st.session_state.all_daily = all_daily
        st.session_state.airlink_records = airlink_records
        st.session_state.moenv_records = moenv_records
        st.session_state.result_df = result_df
        st.session_state.available_stations = available_stations
        st.session_state.start_dt = start_dt
        st.session_state.end_dt = end_dt
        st.session_state.pivot_pm25 = pivot_pm25
        st.session_state.pivot_pm10 = pivot_pm10

    except Exception as e:
        st.error("❌ 發生錯誤: " + str(e))
        import traceback

        st.code(traceback.format_exc())

if st.session_state.data_loaded:
    all_daily = st.session_state.all_daily
    airlink_records = st.session_state.airlink_records
    moenv_records = st.session_state.moenv_records
    result_df = st.session_state.result_df
    available_stations = st.session_state.available_stations
    start_dt = st.session_state.start_dt
    end_dt = st.session_state.end_dt
    pivot_pm25 = st.session_state.pivot_pm25
    pivot_pm10 = st.session_state.pivot_pm10

    st.subheader("📅 每日平均值")
    st.dataframe(result_df, use_container_width=True, height=400)

    st.subheader("📈 趨勢分析")
    view_mode = st.radio("選擇時間刻度", ["每日平均", "每小時平均"], horizontal=True)

    if view_mode == "每日平均":
        fig_pm25 = go.Figure()
        for station in available_stations:
            station_data = all_daily[all_daily['device'] == station].sort_values('date')
            fig_pm25.add_trace(
                go.Scatter(x=station_data['date'], y=station_data['PM2.5'], mode='lines+markers', name=station,
                           line=dict(width=3), marker=dict(size=8)))
        fig_pm25.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="法規標準 30")
        fig_pm25.update_layout(title="PM2.5 每日平均趨勢", xaxis_title="日期", yaxis_title="PM2.5", height=450)
        st.plotly_chart(fig_pm25, use_container_width=True)

        fig_pm10 = go.Figure()
        for station in available_stations:
            station_data = all_daily[all_daily['device'] == station].sort_values('date')
            fig_pm10.add_trace(
                go.Scatter(x=station_data['date'], y=station_data['PM10'], mode='lines+markers', name=station,
                           line=dict(width=3), marker=dict(size=8)))
        fig_pm10.add_hline(y=75, line_dash="dash", line_color="red", annotation_text="法規標準 75")
        fig_pm10.update_layout(title="PM10 每日平均趨勢", xaxis_title="日期", yaxis_title="PM10", height=450)
        st.plotly_chart(fig_pm10, use_container_width=True)

    else:
        st.info("📊 顯示每小時平均值")

        # 準備每小時資料
        hourly_records = []
        for record in airlink_records:
            if 'datetime' in record:
                dt = pd.to_datetime(record['datetime'])
                hour_str = dt.strftime("%Y/%m/%d %H:00")
                date_str = dt.strftime("%Y/%m/%d")
                hourly_records.append({
                    'device': record['device'],
                    'datetime': hour_str,
                    'date': date_str,
                    'PM2.5': record.get('PM2.5'),
                    'PM10': record.get('PM10')
                })

        for record in moenv_records:
            try:
                dt = pd.to_datetime(record['monitordate'])
                hour_str = dt.strftime("%Y/%m/%d %H:00")
                date_str = dt.strftime("%Y/%m/%d")
                itemid = str(record['itemid'])
                station_name = record.get('station_name', '')
                concentration = clean_concentration(record.get('concentration'))
                if concentration is not None:
                    hourly_records.append({
                        'device': station_name,
                        'datetime': hour_str,
                        'date': date_str,
                        'PM2.5': concentration if itemid == '33' else None,
                        'PM10': concentration if itemid == '4' else None
                    })
            except:
                pass

        if hourly_records:
            hourly_df = pd.DataFrame(hourly_records)
            hourly_avg = hourly_df.groupby(['device', 'datetime', 'date']).agg(
                {'PM2.5': 'mean', 'PM10': 'mean'}).reset_index()

            # 轉換為 datetime 物件後排序
            hourly_avg['datetime_sort'] = pd.to_datetime(hourly_avg['datetime'])
            hourly_avg = hourly_avg.sort_values('datetime_sort').reset_index(drop=True)

            # 取得所有可用的日期
            available_dates = sorted(hourly_avg['date'].unique())

            # 日期選擇下拉選單
            selected_date = st.selectbox(
                "選擇日期",
                options=available_dates,
                index=0
            )

            # 篩選選定日期的資料，並確保排序正確
            filtered_hourly = hourly_avg[hourly_avg['date'] == selected_date].copy()
            filtered_hourly = filtered_hourly.sort_values('datetime_sort').reset_index(drop=True)

            if not filtered_hourly.empty:
                # PM2.5 每小時平均趨勢
                # PM2.5 每小時平均趨勢
                fig_pm25_h = go.Figure()
                for station in available_stations:
                    data = filtered_hourly[filtered_hourly['device'] == station].dropna(subset=['PM2.5'])
                    if not data.empty:
                        fig_pm25_h.add_trace(go.Scatter(
                            x=data['datetime_sort'],  # 改用 datetime_sort
                            y=data['PM2.5'],
                            mode='lines+markers',
                            name=station,
                            line=dict(width=2),
                            marker=dict(size=6)
                        ))
                fig_pm25_h.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="法規標準 30")
                fig_pm25_h.update_layout(
                    title="PM2.5 每小時平均趨勢 - " + selected_date,
                    xaxis_title="時間",
                    yaxis_title="PM2.5 (μg/m³)",
                    height=450,
                    xaxis=dict(
                        tickangle=-45,
                        tickformat='%H:%M'  # 只顯示時間
                    )
                )
                st.plotly_chart(fig_pm25_h, use_container_width=True)

                # PM10 每小時平均趨勢
                fig_pm10_h = go.Figure()
                for station in available_stations:
                    data = filtered_hourly[filtered_hourly['device'] == station].dropna(subset=['PM10'])
                    if not data.empty:
                        fig_pm10_h.add_trace(go.Scatter(
                            x=data['datetime_sort'],  # 改用 datetime_sort
                            y=data['PM10'],
                            mode='lines+markers',
                            name=station,
                            line=dict(width=2),
                            marker=dict(size=6)
                        ))
                fig_pm10_h.add_hline(y=75, line_dash="dash", line_color="red", annotation_text="法規標準 75")
                fig_pm10_h.update_layout(
                    title="PM10 每小時平均趨勢 - " + selected_date,
                    xaxis_title="時間",
                    yaxis_title="PM10 (μg/m³)",
                    height=450,
                    xaxis=dict(
                        tickangle=-45,
                        tickformat='%H:%M'
                    )
                )
                st.plotly_chart(fig_pm10_h, use_container_width=True)

                st.caption("📊 " + selected_date + " 共顯示 " + str(len(filtered_hourly)) + " 個小時的平均資料")
            else:
                st.warning("⚠️ " + selected_date + " 沒有資料")
        else:
            st.warning("⚠️ 沒有每小時資料")

    st.divider()
    st.subheader("📊 統計摘要")
    pm25_stats = {'測站': [], '最小': [], '最大': []}
    pm10_stats = {'測站': [], '最小': [], '最大': []}
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_stats['測站'].append(station)
            pm25_stats['最小'].append(int(station_data['PM2.5'].min()))
            pm25_stats['最大'].append(int(station_data['PM2.5'].max()))
            pm10_stats['測站'].append(station)
            pm10_stats['最小'].append(int(station_data['PM10'].min()))
            pm10_stats['最大'].append(int(station_data['PM10'].max()))

    pm25_df = pd.DataFrame(pm25_stats).set_index('測站').T
    pm10_df = pd.DataFrame(pm10_stats).set_index('測站').T

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**PM2.5 (法規標準: 30μg/m³)**")
        st.dataframe(pm25_df, use_container_width=True, height=100)
    with col2:
        st.markdown("**PM10 (法規標準: 75μg/m³)**")
        st.dataframe(pm10_df, use_container_width=True, height=100)

    st.subheader("💾 匯出資料")

    # 準備 CSV 內容
    csv_lines = []

    # 第一部分：原始每小時資料
    csv_lines.append("========== 原始每小時資料 ==========")
    csv_lines.append("")

    hourly_header = ['日期時間', '測站', 'PM2.5', 'PM10']
    csv_lines.append(','.join(hourly_header))

    # 合併 AirLink 和環保署的每小時資料
    all_hourly = []

    for record in airlink_records:
        if 'datetime' in record:
            all_hourly.append({
                'datetime': record['datetime'],
                'device': record['device'],
                'PM2.5': record.get('PM2.5', ''),
                'PM10': record.get('PM10', '')
            })

    for record in moenv_records:
        try:
            datetime_str = pd.to_datetime(record['monitordate']).strftime("%Y/%m/%d %H:%M")
            itemid = str(record['itemid'])
            station_name = record.get('station_name', '')
            concentration = clean_concentration(record.get('concentration'))

            if concentration is not None:
                existing = next(
                    (r for r in all_hourly if r['datetime'] == datetime_str and r['device'] == station_name), None)
                if existing:
                    if itemid == '33':
                        existing['PM2.5'] = concentration
                    elif itemid == '4':
                        existing['PM10'] = concentration
                else:
                    all_hourly.append({
                        'datetime': datetime_str,
                        'device': station_name,
                        'PM2.5': concentration if itemid == '33' else '',
                        'PM10': concentration if itemid == '4' else ''
                    })
        except:
            pass

    hourly_df_export = pd.DataFrame(all_hourly)
    if not hourly_df_export.empty:
        hourly_df_export['datetime_sort'] = pd.to_datetime(hourly_df_export['datetime'])
        hourly_df_export = hourly_df_export.sort_values(['device', 'datetime_sort'])

        for _, row in hourly_df_export.iterrows():
            pm25_val = str(round(row['PM2.5'], 1)) if pd.notna(row['PM2.5']) and row['PM2.5'] != '' else ''
            pm10_val = str(round(row['PM10'], 1)) if pd.notna(row['PM10']) and row['PM10'] != '' else ''
            csv_lines.append(','.join([row['datetime'], row['device'], pm25_val, pm10_val]))

    csv_lines.append("")
    csv_lines.append("")

    # 第二部分：每日平均彙整表
    csv_lines.append("========== 每日平均彙整表 ==========")
    csv_lines.append("")

    header = ['日期'] + ['PM2.5', 'PM10'] * len(available_stations)
    csv_lines.append(','.join(header))

    subheader = ['']
    for station in available_stations:
        subheader.extend([station, ''])
    csv_lines.append(','.join(subheader))

    for _, row in result_df.iterrows():
        row_data = [row['日期']]
        for station in available_stations:
            pm25_col = station + '_PM2.5'
            pm10_col = station + '_PM10'
            row_data.append(str(int(row[pm25_col])) if pd.notna(row[pm25_col]) else '')
            row_data.append(str(int(row[pm10_col])) if pd.notna(row[pm10_col]) else '')
        csv_lines.append(','.join(row_data))

    csv_lines.append("")
    csv_lines.append("")

    # 第三部分：統計摘要
    csv_lines.append("========== 統計摘要 ==========")
    csv_lines.append("")
    csv_lines.append("查詢日期: " + start_dt.strftime('%Y/%m/%d') + " ~ " + end_dt.strftime('%Y/%m/%d'))
    csv_lines.append("")

    pm25_header = ['PM2.5'] + available_stations
    csv_lines.append(','.join(pm25_header))

    pm25_min_row = ['最小值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_min_row.append(str(int(station_data['PM2.5'].min())))
        else:
            pm25_min_row.append('')
    csv_lines.append(','.join(pm25_min_row))

    pm25_max_row = ['最大值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_max_row.append(str(int(station_data['PM2.5'].max())))
        else:
            pm25_max_row.append('')
    csv_lines.append(','.join(pm25_max_row))

    pm25_avg_row = ['平均值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_avg_row.append(str(int(station_data['PM2.5'].mean())))
        else:
            pm25_avg_row.append('')
    csv_lines.append(','.join(pm25_avg_row))

    csv_lines.append("")

    pm10_header = ['PM10'] + available_stations
    csv_lines.append(','.join(pm10_header))

    pm10_min_row = ['最小值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm10_min_row.append(str(int(station_data['PM10'].min())))
        else:
            pm10_min_row.append('')
    csv_lines.append(','.join(pm10_min_row))

    pm10_max_row = ['最大值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm10_max_row.append(str(int(station_data['PM10'].max())))
        else:
            pm10_max_row.append('')
    csv_lines.append(','.join(pm10_max_row))

    pm10_avg_row = ['平均值']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm10_avg_row.append(str(int(station_data['PM10'].mean())))
        else:
            pm10_avg_row.append('')
    csv_lines.append(','.join(pm10_avg_row))

    csv_lines.append("")
    csv_lines.append("註：PM2.5 法規標準 30μg/m³，PM10 法規標準 75μg/m³")

    csv_content = '\n'.join(csv_lines)
    filename = "空品完整資料_" + start_dt.strftime('%Y%m%d') + "_" + end_dt.strftime('%Y%m%d') + ".csv"

    st.download_button(
        "📥 下載完整 CSV 檔案（含原始資料）",
        data=csv_content.encode('utf-8-sig'),
        file_name=filename,
        mime="text/csv",
        use_container_width=True
    )

    for _, row in result_df.iterrows():
        date_parts = row['日期'].split('/')
        year = int(date_parts[0]) - 1911
        month = int(date_parts[1])
        day = int(date_parts[2])
        date_display = str(year) + "/" + str(month) + "/" + str(day)
        row_data = [date_display]
        for station in available_stations:
            pm25_col = station + '_PM2.5'
            pm10_col = station + '_PM10'
            row_data.append(str(int(row[pm25_col])) if pd.notna(row[pm25_col]) else '')
            row_data.append(str(int(row[pm10_col])) if pd.notna(row[pm10_col]) else '')
        csv_lines.append(','.join(row_data))

    csv_lines.append('')
    csv_lines.append(start_dt.strftime('%Y/%m/%d') + "~" + end_dt.strftime('%Y/%m/%d'))

    pm25_header = ['PM2.5'] + available_stations
    csv_lines.append(','.join(pm25_header))
    pm25_min_row = ['最小']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_min_row.append(str(int(station_data['PM2.5'].min())))
        else:
            pm25_min_row.append('')
    csv_lines.append(','.join(pm25_min_row))

    pm25_max_row = ['最大']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm25_max_row.append(str(int(station_data['PM2.5'].max())))
        else:
            pm25_max_row.append('')
    csv_lines.append(','.join(pm25_max_row))

    pm10_header = ['PM10'] + available_stations
    csv_lines.append(','.join(pm10_header))
    pm10_min_row = ['最小']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm10_min_row.append(str(int(station_data['PM10'].min())))
        else:
            pm10_min_row.append('')
    csv_lines.append(','.join(pm10_min_row))

    pm10_max_row = ['最大']
    for station in available_stations:
        station_data = all_daily[all_daily['device'] == station]
        if not station_data.empty:
            pm10_max_row.append(str(int(station_data['PM10'].max())))
        else:
            pm10_max_row.append('')
    csv_lines.append(','.join(pm10_max_row))
    csv_lines.append('註：超過空氣品質標準以粗體表示')

    csv_content = '\n'.join(csv_lines)
    filename = "空品_" + start_dt.strftime('%Y%m%d') + "_" + end_dt.strftime('%Y%m%d') + ".csv"
    st.download_button("📥 下載 CSV 檔案", data=csv_content.encode('utf-8-sig'), file_name=filename, mime="text/csv",
                       use_container_width=True)

else:
    st.info("👈 請在左側選擇查詢日期，然後點擊「開始查詢」按鈕")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 📋 功能特色\n- 整合 AirLink 與環保署資料\n- 即時查詢與視覺化\n- CSV 匯出功能\n- 趨勢圖表分析")
    with col2:
        st.markdown("### 🎯 測站資訊\n- **AirLink**: 南區上、南區下\n- **環保署**: 仁武、楠梓\n- 支援自訂日期範圍")
    with col3:
        st.markdown("### 📊 資料呈現\n- 每日/每小時平均趨勢圖\n- 統計摘要與比較\n- 匯出 CSV 報表")