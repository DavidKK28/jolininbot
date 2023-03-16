import os
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, TextSendMessage, AudioSendMessage
import openai
from azure.cognitiveservices.speech import SpeechConfig, SpeechSynthesizer, AudioConfig, SpeechRecognizer, AudioDataStream
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
from io import BytesIO
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

openai.api_key = os.getenv('OPENAI_API_KEY')

speech_config = SpeechConfig(subscription=os.getenv("AZURE_SPEECH_SUBSCRIPTION_KEY"), region=os.getenv("AZURE_SPEECH_REGION"))

blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AZURE_BLOB_CONNECTION_STRING"))
container_client = blob_service_client.get_container_client("your-container-name")

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    text = event.message.text
    reply_text = process_text(text)
    audio_url = text_to_speech(reply_text)

    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=reply_text),
            AudioSendMessage(original_content_url=audio_url, duration=1000),
        ],
    )

@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    audio_content = line_bot_api.get_message_content(event.message.id)
    text = speech_to_text(audio_content.content)
    reply_text = process_text(text)
    audio_url = text_to_speech(reply_text)

    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=reply_text),
            AudioSendMessage(original_content_url=audio_url, duration=1000),
        ],
    )

def process_text(text):
    prompt = f"User: {text}\nBot:"
    response = openai.Completion.create(
        engine="text-davinci-002",
        prompt=prompt,
        max_tokens=100,
        n=1,
        stop=None,
        temperature=0.5,
    )
    return response.choices[0].text.strip()

def text_to_speech(text):
    audio_config = AudioConfig(stream=BytesIO())
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    synthesizer.speak_text_async(text).get()
    audio_data = audio_config.stream.getvalue()
    audio_url = upload_to_temporary_storage(audio_data)
    return audio_url

def speech_to_text(audio_content):
    audio_input = AudioDataStream.from_bytes(audio_content)
    recognizer = SpeechRecognizer(speech_config=speech_config, audio_config=audio_input)
    result = recognizer.recognize_once_async().get()
    return result.text.strip()

def upload_to_temporary_storage(audio_data):
    blob_name = f"audio-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.wav"
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(audio_data)

    sas_token = generate_blob_sas(
        blob_service_client.account_name,
        container_client.container_name,
        blob_name,
        account_key=blob_service_client.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )

    audio_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{container_client.container_name}/{blob_name}?{sas_token}"
    return audio_url

if __name__ == "__main__":
    app.run()