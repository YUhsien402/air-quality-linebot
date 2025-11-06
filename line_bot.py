#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
南區案空氣品質監測系統 - LINE Bot
提供即時空品查詢、歷史資料分析、測站資訊等功能
"""

from flask import Flask, request, abort
import os
from dotenv import load_dotenv

# LINE Bot SDK v3
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    TemplateMessage,
    ButtonsTemplate,
    URIAction,
    MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ⭐ 匯入 API 模組
from air_quality_api import (
    get_current_airlink_data,
    get_current_moenv_data,
    format_air_quality_message,
    format_station_info
)

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# LINE Bot 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LIFF_ID = os.getenv('LIFF_ID', '')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    print("⚠️  警告：請在環境變數中設定 LINE 憑證")
else:
    print("✅ LINE Bot 設定已載入")

LIFF_URL = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else "https://your-streamlit-app.com"

# 初始化 LINE Bot v3
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ==================== 首頁 ====================

@app.route("/")
def home():
    """首頁 - 顯示服務狀態"""
    return """
    <html>
    <head>
        <title>南區案空氣品質監測系統</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body { 
                font-family: 'Microsoft JhengHei', 'Segoe UI', Arial, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }
            .container {
                background: white;
                color: #333;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                max-width: 700px;
                width: 100%;
                animation: fadeIn 0.5s ease-in;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            h1 { 
                color: #667eea;
                margin-bottom: 10px;
                font-size: 2em;
                text-align: center;
            }
            .subtitle {
                color: #999;
                text-align: center;
                margin-bottom: 30px;
                font-size: 1.1em;
            }
            .info { 
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                padding: 25px;
                border-radius: 15px;
                margin-top: 20px;
            }
            .status { 
                color: #28a745;
                font-weight: bold;
                font-size: 1.2em;
                margin-bottom: 15px;
                text-align: center;
            }
            .info-item {
                margin: 12px 0;
                line-height: 1.8;
                padding: 10px;
                background: rgba(255, 255, 255, 0.6);
                border-radius: 8px;
            }
            .info-item strong {
                color: #667eea;
                display: inline-block;
                min-width: 120px;
            }
            .footer {
                text-align: center;
                margin-top: 30px;
                color: #999;
                font-size: 0.9em;
            }
            .footer p {
                margin: 5px 0;
            }
            code {
                background: #f4f4f4;
                padding: 2px 8px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                color: #667eea;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌫️ 南區案空氣品質監測系統</h1>
            <p class="subtitle">Air Quality Monitoring System</p>
            
            <div class="info">
                <p class="status">✅ LINE Bot 正在運行中...</p>
                
                <div class="info-item">
                    <strong>📝 Webhook:</strong> <code>/callback</code>
                </div>
                
                <div class="info-item">
                    <strong>🎯 監測站點:</strong> 仁武、楠梓、南區上、南區下
                </div>
                
                <div class="info-item">
                    <strong>📊 資料來源:</strong> AirLink、環保署開放資料
                </div>
                
                <div class="info-item">
                    <strong>🔄 更新頻率:</strong> AirLink 每 5 分鐘，環保署每小時
                </div>
                
                <div class="info-item">
                    <strong>💬 使用方式:</strong> 在 LINE 中傳送「開始」或「hi」
                </div>
            </div>
            
            <div class="footer">
                <p><strong>Powered by LINE Messaging API</strong></p>
                <p>© 2025 南區案空氣品質監測系統</p>
                <p>All Rights Reserved</p>
            </div>
        </div>
    </body>
    </html>
    """


# ==================== Webhook ====================

@app.route("/callback", methods=['GET', 'POST'])
def callback():
    """處理 LINE Webhook 請求"""
    # 處理 GET 請求（健康檢查）
    if request.method == 'GET':
        return 'OK', 200
    
    # 處理 POST 請求（LINE 訊息）
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    print(f"📨 收到 Webhook 請求")
    print(f"📋 Body: {body[:100]}...")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")
        abort(400)
    except Exception as e:
        print(f"❌ 處理錯誤: {e}")
        import traceback
        traceback.print_exc()
        abort(500)
    
    return 'OK'


# ==================== 訊息處理 ====================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理使用者訊息"""
    user_text = event.message.text.strip()
    print(f"💬 收到訊息: {user_text}")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        # ==================== 主選單 ====================
        if user_text in ["開始", "選單", "menu", "查詢", "hi", "hello", "你好", "Hello", "哈囉", "start"]:
            buttons_template = ButtonsTemplate(
                title='🌫️ 空氣品質查詢系統',
                text='請選擇功能',
                actions=[
                    URIAction(
                        label='📊 開啟查詢系統',
                        uri=LIFF_URL
                    ),
                    MessageAction(
                        label='📅 今日空品',
                        text='今日'
                    ),
                    MessageAction(
                        label='❓ 使用說明',
                        text='說明'
                    )
                ]
            )
            
            template_message = TemplateMessage(
                alt_text='空氣品質查詢系統選單',
                template=buttons_template
            )
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[template_message]
                )
            )
        
        # ==================== 今日空品（即時資料）====================
        elif user_text in ["今日", "即時", "現在", "空品", "查詢空品", "空氣品質", "今日空品"]:
            print("📡 開始取得即時空氣品質資料...")
            
            # 取得 API 金鑰
            api_key = os.getenv('API_KEY', '')
            api_secret = os.getenv('API_SECRET', '')
            station_id = os.getenv('STATION_ID', '')
            moenv_token = os.getenv('MOENV_API_TOKEN', '')
            
            # 檢查 API 設定
            if not all([api_key, api_secret, station_id, moenv_token]):
                reply_text = ("⚠️ 系統設定不完整\n\n"
                             "無法取得即時資料\n\n"
                             "💡 您可以：\n"
                             "• 點擊「開啟查詢系統」查看歷史資料\n"
                             "• 聯絡系統管理員")
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
                return
            
            try:
                # 取得 AirLink 資料
                print("📡 正在取得 AirLink 資料...")
                airlink_data = get_current_airlink_data(api_key, api_secret, station_id)
                print(f"📊 AirLink 資料: {airlink_data}")
                
                # 取得環保署資料
                print("📡 正在取得環保署資料...")
                moenv_data = get_current_moenv_data(moenv_token)
                print(f"📊 環保署資料: {moenv_data}")
                
                # 合併資料
                all_data = {}
                if airlink_data:
                    all_data.update(airlink_data)
                if moenv_data:
                    all_data.update(moenv_data)
                
                # 格式化訊息
                reply_text = format_air_quality_message(all_data)
                
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
            except Exception as e:
                print(f"❌ API 呼叫錯誤: {e}")
                import traceback
                traceback.print_exc()
                
                error_text = ("❌ 取得資料時發生錯誤\n\n"
                             "請稍後再試\n\n"
                             "💡 您也可以點擊「開啟查詢系統」\n"
                             "查看歷史資料")
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=error_text)]
                    )
                )
        
        # ==================== 測站資訊 ====================
        elif user_text in ["測站", "測站資訊", "站點", "監測站", "監測站點"]:
            print("📍 顯示測站資訊...")
            
            # 使用 API 模組的測站資訊函數
            stations_text = format_station_info()
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=stations_text)]
                )
            )
        
        # ==================== 使用說明 ====================
        elif user_text in ["說明", "help", "Help", "使用說明", "教學", "指令"]:
            help_text = """🌫️ 空氣品質查詢系統

📱 主要功能：
━━━━━━━━━━━━
✅ 即時空氣品質查詢
✅ 歷史資料分析
✅ 趨勢圖表檢視
✅ 多測站比較
✅ 資料匯出功能

🎯 監測站點：
━━━━━━━━━━━━
📍 AirLink: 南區上、南區下
📍 環保署: 仁武、楠梓

📊 使用方式：
━━━━━━━━━━━━
1️⃣ 輸入「今日」或「即時」
   → 查看即時空品資料

2️⃣ 輸入「測站」
   → 查看測站詳細資訊

3️⃣ 輸入「選單」或「開始」
   → 顯示功能選單

4️⃣ 點擊「開啟查詢系統」
   → 查看完整歷史資料
   → 自訂日期範圍
   → 圖表趨勢分析
   → 匯出 CSV 檔案

📌 空品標準：
━━━━━━━━━━━━
• PM2.5 ≤ 30 μg/m³ (法規標準)
• PM10  ≤ 75 μg/m³ (法規標準)

🔄 更新頻率：
━━━━━━━━━━━━
• AirLink: 每 5 分鐘
• 環保署: 每小時

💡 小提示：
━━━━━━━━━━━━
• 在 LINE 中開啟可獲得最佳體驗
• 可使用 Rich Menu（下方選單）快速操作
• 支援多種指令觸發詞

🌟 快速指令：
━━━━━━━━━━━━
• 今日 / 即時 / 空品 → 即時資料
• 測站 → 測站資訊
• 選單 → 功能選單
• 說明 → 此說明

有任何問題歡迎隨時詢問！"""
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=help_text)]
                )
            )
        
        # ==================== 其他訊息 ====================
        else:
            reply_text = (f"💬 您說：{user_text}\n\n"
                         "━━━━━━━━━━━━\n\n"
                         "🔍 可用指令：\n"
                         "• 「今日」或「即時」→ 查看即時空品\n"
                         "• 「測站」→ 查看測站資訊\n"
                         "• 「選單」或「開始」→ 顯示功能選單\n"
                         "• 「說明」→ 查看使用說明\n\n"
                         "💡 或點擊下方選單按鈕快速操作")
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )


# ==================== 主程式 ====================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print("")
    print("=" * 60)
    print("🚀 南區案空氣品質監測系統 - LINE Bot")
    print("=" * 60)
    print("")
    print(f"📡 本地測試: http://localhost:{port}")
    print(f"📝 Webhook URL: http://localhost:{port}/callback")
    print("")
    print("✅ LINE Bot 設定已載入")
    print(f"✅ LIFF URL: {LIFF_URL}")
    print("")
    print("📋 可用指令：")
    print("   • 今日/即時/空品 → 即時空品資料")
    print("   • 測站 → 測站資訊")
    print("   • 選單/開始/hi → 功能選單")
    print("   • 說明/help → 使用說明")
    print("")
    print("=" * 60)
    print("🎯 等待連線中...")
    print("=" * 60)
    print("")
    
    app.run(host='0.0.0.0', port=port, debug=False)
