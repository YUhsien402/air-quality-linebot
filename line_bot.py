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
    format_air_quality_message
)

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# LINE Bot 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')
LIFF_ID = os.getenv('LIFF_ID', '')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    print("⚠️  警告：請在 .env 檔案中設定 LINE 憑證")
else:
    print("✅ LINE Bot 設定已載入")

LIFF_URL = f"https://liff.line.me/{LIFF_ID}" if LIFF_ID else "https://your-streamlit-app.com"

# 初始化 LINE Bot v3
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/")
def home():
    return """
    <html>
    <head>
        <title>空氣品質查詢系統</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 50px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: white;
                color: #333;
                padding: 30px;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }
            h1 { color: #667eea; }
            .info { 
                background: #f0f0f0; 
                padding: 15px; 
                border-radius: 5px; 
                margin-top: 20px;
            }
            .status { color: #28a745; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌫️ 南區案空氣品質查詢系統</h1>
            <div class="info">
                <p class="status">✅ LINE Bot 正在運行中...</p>
                <p>📝 Webhook URL: <code>/callback</code></p>
                <p>🎯 監測站點: 仁武、楠梓、南區上、南區下</p>
                <p>💬 請在 LINE 中傳送「開始」或「hi」測試</p>
            </div>
        </div>
    </body>
    </html>
    """

@app.route("/callback", methods=['GET', 'POST'])
def callback():
    # 處理 GET 請求（用於健康檢查或驗證）
    if request.method == 'GET':
        return 'OK', 200
    
    # 處理 POST 請求
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    print(f"📨 收到 Webhook 請求")
    print(f"📋 Body: {body[:100]}...")  # 顯示前100個字元
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")
        abort(400)
    except Exception as e:
        print(f"❌ 處理錯誤: {e}")
        abort(500)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    print(f"💬 收到訊息: {user_text}")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        # 主選單
        if user_text in ["開始", "選單", "menu", "查詢", "hi", "hello", "你好"]:
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
        
        # ⭐ 今日空品（即時資料）
        elif user_text in ["今日", "即時", "現在", "空品"]:
            print("📡 開始取得即時空氣品質資料...")
            
            # 取得 API 金鑰
            api_key = os.getenv('API_KEY', '')
            api_secret = os.getenv('API_SECRET', '')
            station_id = os.getenv('STATION_ID', '')
            moenv_token = os.getenv('MOENV_API_TOKEN', '')
            
            # 檢查 API 設定
            if not all([api_key, api_secret, station_id, moenv_token]):
                reply_text = "⚠️ 系統設定不完整\n\n請稍後再試或聯絡管理員\n\n💡 您也可以點擊「開啟查詢系統」\n查看歷史資料"
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
                return
            
            # 取得 AirLink 資料
            airlink_data = get_current_airlink_data(api_key, api_secret, station_id)
            print(f"📊 AirLink 資料: {airlink_data}")
            
            # 取得環保署資料
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
        
        # 使用說明
        elif user_text == "說明":
            help_text = """🌫️ 空氣品質查詢系統使用說明

📱 功能特色：
✅ 即時空氣品質數據
✅ 多測站比較分析
✅ 趨勢圖表檢視
✅ 資料匯出功能

🎯 監測站點：
- AirLink: 南區上、南區下
- 環保署: 仁武、楠梓

📊 使用方式：
1. 輸入「今日」或「即時」查看即時空品
2. 輸入「選單」查看功能
3. 點擊「開啟查詢系統」查看歷史資料
4. 選擇查詢日期範圍
5. 查看數據與圖表

💡 提示：
在 LINE 中開啟可獲得最佳體驗！"""
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=help_text)]
                )
            )
        
        # 其他訊息
        else:
            reply_text = f"您說：{user_text}\n\n💡 輸入「開始」或「選單」查看功能\n💡 輸入「今日」查看即時空品"
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print("")
    print("=" * 50)
    print("🚀 LINE Bot 啟動成功！")
    print(f"📡 本地測試: http://localhost:{port}")
    print(f"📝 Webhook URL: http://localhost:{port}/callback")
    print("=" * 50)
    print("")
    app.run(host='0.0.0.0', port=port, debug=False)
