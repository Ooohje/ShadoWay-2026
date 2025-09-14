# run_ngrok.py
from pyngrok import ngrok

ngrok.set_auth_token("32MEUCV9b8XVgmeY3qbnIEXAagR_4XBCxTW5t4z5McoijHFc8")
public_url = ngrok.connect(8501, "http")  # Streamlit이 8501에서 실행 중이어야 함
print("Public URL:", public_url)
input("Press Enter to quit...")
