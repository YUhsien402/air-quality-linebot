#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正版 LINE Bot - 解決歷史查詢超時問題
"""

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import os
import datetime
import re
import threading

# 導入模組
from air_quality_api import get_current_airlink_data, get_current_moenv_data, format_air_quality_message, format_station_info
from historical_query import query_historical_data

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

def create_main_menu_quick_reply():
    """主選單"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="📊 今日空品", text="今日")),
        QuickReplyButton(action=MessageAction(label="📅 歷史查詢", text="歷史查詢")),
        QuickReplyButton(action=MessageAction(label="📍 測站資訊", text="測站資訊")),
        QuickReplyButton(action=MessageAction(label="🌐 開啟系統", text="開啟查詢系統"))
    ])

def create_date_range_examples_quick_reply():
    """日期範圍快速回覆"""
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    week_ago = today - datetime.timedelta(days=7)
    
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="昨天", text=f"{yesterday.strftime('%Y/%m/%d')}-{yesterday.strftime('%Y/%m/%d')}")),
        QuickReplyButton(action=MessageAction(label="最近3天", text=f"{(today-datetime.timedelta(days=3)).strftime('%Y/%m/%d')}-{yesterday.strftime('%Y/%m/%d')}")),
        QuickReplyButton(action=MessageAction(label="最近7天", text=f"{week_ago.strftime('%Y/%m/%d')}-{yesterday.strftime('%Y/%m/%d')}")),
        QuickReplyButton(action=MessageAction(label="取消", text="選單"))
    ])

def parse_date_range(text: str) -> tuple:
    """解析日期範圍"""
    try:
        text = text.strip()
        
        # 格式: YYYY/MM/DD-YYYY/MM/DD
        pattern1 = r'(\d{3,4})/(\d{1,2})/(\d{1,2})-(\d{3,4})/(\d{1,2})/(\d{1,2})'
        match = re.match(pattern1, text)
        if match:
            y1, m1, d1, y2, m2, d2 = match.groups()
            y1, y2 = int(y1), int(y2)
            if y1 < 1000:
                y1 += 1911
            if y2 < 1000:
                y2 += 1911
            start_date = datetime.date(y1, int(m1), int(d1))
            end_date = datetime.date(y2, int(m2), int(d2))
            return (start_date, end_date)
        
        # 格式: MM/DD-MM/DD
        pattern2 = r'(\d{1,2})/(\d{1,2})-(\d{1,2})/(\d{1,2})'
        match = re.match(pattern2, text)
        if match:
            m1, d1, m2, d2 = match.groups()
            current_year = datetime.date.today().year
            start_date = datetime.date(current_year, int(m1), int(d1))
            end_date = datetime.date(current_year, int(m2), int(d2))
            return (start_date, end_date)
        
        return (None, None)
    except:
        return (None, None)

def query_historical_async(user_id: str, start_date: datetime.date, end_date: datetime.date):
    """
    🔥 關鍵修正：在背景執行查詢
    """
    try:
        print(f"🔍 開始查詢歷史資料: {start_date} ~ {end_date}")
        
        # 執行查詢
        result = query_historical_data(
            API_KEY, API_SECRET, STATION_ID,
            MOENV_API_TOKEN, start_date, end_date
        )
        
        print(f"✅ 查詢完成，結果長度: {len(result)} 字元")
        
        # 檢查長度
        if len(result) > 4500:
            # 分段傳送
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
            
            # 傳送多則訊息
            for i, part in enumerate(parts):
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(
                        text=part,
                        quick_reply=create_main_menu_quick_reply() if i == len(parts)-1 else None
                    )
                )
        else:
            # 單則訊息
            line_bot_api.push_message(
                user_id,
                TextSendMessage(
                    text=result,
                    quick_reply=create_main_menu_quick_reply()
                )
            )
        
    except Exception as e:
        print(f"❌ 查詢異常: {e}")
        import traceback
        traceback.print_exc()
        
        # 傳送錯誤訊息
        line_bot_api.push_message(
            user_id,
            TextSendMessage(
                text=f"❌ 查詢失敗\n\n錯誤: {str(e)}\n\n請稍後再試或聯絡管理員",
                quick_reply=create_main_menu_quick_reply()
            )
        )

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
    
    # 處理歷史查詢流程
    if user_state.get('waiting_for_date_range'):
        start_date, end_date = parse_date_range(text)
        
        if start_date and end_date:
            # 驗證
            if start_date > end_date:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="❌ 開始日期不能晚於結束日期\n\n請重新輸入",
                        quick_reply=create_date_range_examples_quick_reply()
                    )
                )
                return
            
            if (end_date - start_date).days > 30:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="❌ 查詢範圍不能超過 30 天\n\n請重新輸入",
                        quick_reply=create_date_range_examples_quick_reply()
                    )
                )
                return
            
            # 清除狀態
            user_states[user_id] = {}
            
            # 🔥 關鍵修正：先回應，再在背景查詢
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"🔍 正在查詢 {start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')} 的資料\n\n⏳ 預計需要 10-30 秒，請稍候...")
            )
            
            # 在背景執行查詢
            thread = threading.Thread(
                target=query_historical_async,
                args=(user_id, start_date, end_date)
            )
            thread.daemon = True
            thread.start()
            
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="❌ 日期格式錯誤\n\n請使用：2025/10/01-2025/10/07",
                    quick_reply=create_date_range_examples_quick_reply()
                )
            )
        return
    
    # 處理一般指令
    if text in ["今日", "今天", "即時", "現在"]:
        airlink_data = get_current_airlink_data(API_KEY, API_SECRET, STATION_ID)
        moenv_data = get_current_moenv_data(MOENV_API_TOKEN)
        
        all_data = {}
        if airlink_data:
            all_data.update(airlink_data)
        if moenv_data:
            all_data.update(moenv_data)
        
        message = format_air_quality_message(all_data)
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply())
        )
    
    elif text in ["歷史查詢", "歷史資料", "查詢歷史"]:
        user_states[user_id] = {'waiting_for_date_range': True}
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="📅 請輸入查詢日期範圍\n\n" +
                     "格式範例：\n" +
                     "• 2025/10/01-2025/10/07\n" +
                     "• 114/10/01-114/10/07 (民國年)\n" +
                     "• 10/01-10/07 (省略年份)\n\n" +
                     "⚠️ 最多可查詢 30 天\n" +
                     "💡 建議查詢 7 天以內較快",
                quick_reply=create_date_range_examples_quick_reply()
            )
        )
    
    elif text in ["測站資訊", "測站", "站點"]:
        message = format_station_info()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply())
        )
    
    elif text in ["選單", "主選單", "功能", "menu"]:
        message = (
            "🌟 南區案空氣品質查詢系統\n\n"
            "請選擇功能：\n\n"
            "📊 今日空品 - 查看即時空氣品質\n"
            "📅 歷史查詢 - 查詢過去資料\n"
            "📍 測站資訊 - 查看測站詳細資訊\n"
            "🌐 開啟系統 - 開啟完整查詢系統"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply())
        )
    
    elif text in ["開啟查詢系統", "開啟系統", "系統", "查詢系統"]:
        if LIFF_ID:
            liff_url = f"https://liff.line.me/{LIFF_ID}"
            message = f"🌐 請點擊連結開啟完整查詢系統：\n{liff_url}\n\n可查看詳細趨勢圖表與匯出資料"
        else:
            message = "⚠️ 查詢系統尚未設定"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply())
        )
    
    else:
        # 嘗試直接解析日期
        start_date, end_date = parse_date_range(text)
        
        if start_date and end_date:
            if (end_date - start_date).days > 30:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="❌ 查詢範圍不能超過 30 天",
                        quick_reply=create_main_menu_quick_reply()
                    )
                )
                return
            
            # 先回應
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"🔍 正在查詢 {start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')} 的資料\n\n⏳ 預計需要 10-30 秒，請稍候...")
            )
            
            # 背景查詢
            thread = threading.Thread(
                target=query_historical_async,
                args=(user_id, start_date, end_date)
            )
            thread.daemon = True
            thread.start()
        else:
            message = (
                "💡 使用說明\n\n"
                "請輸入以下指令：\n"
                "• 今日 - 查看即時空品\n"
                "• 歷史查詢 - 查詢過去資料\n"
                "• 測站資訊 - 測站詳情\n"
                "• 選單 - 顯示所有功能"
            )
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=message, quick_reply=create_main_menu_quick_reply())
            )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
