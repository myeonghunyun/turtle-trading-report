import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
from email.mime.text import MIMEText

print("스크립트 실행 시작...")

def get_turtle_signal(ticker):
    data = yf.download(ticker, period="1y", auto_adjust=True)

    if data.empty:
        return "데이터 없음", 0, 0, 0, 0

    data['20_high'] = data['High'].rolling(window=20).max()
    data['10_low'] = data['Low'].rolling(window=10).min()

    data['tr1'] = data['High'] - data['Low']
    data['tr2'] = np.abs(data['High'] - data['Close'].shift())
    data['tr3'] = np.abs(data['Low'] - data['Close'].shift())
    data['TrueRange'] = data[['tr1', 'tr2', 'tr3']].max(axis=1)
    data['ATR'] = data['TrueRange'].rolling(window=20).mean()

    last_close = data['Close'].iloc[-1].item()
    last_20_high = data['20_high'].iloc[-1].item()
    last_10_low = data['10_low'].iloc[-1].item()
    last_atr = data['ATR'].iloc[-1].item()

    signal = "보유"
    stop_loss = 0
    target_price = 0

    if last_close > last_20_high:
        signal = "BUY"
        stop_loss = last_close - (2 * last_atr)
        target_price = last_close + (2 * last_atr)

    elif last_close < last_10_low:
        signal = "SELL"

    return signal, last_atr, stop_loss, target_price, last_close

def send_email(subject, body):
    sender_email = "ag9789@gmail.com"
    sender_password = "ahuq zwyc duwy faaz"
    receiver_email = "ag9789@gmail.com"

    msg = MIMEText(body, 'html', _charset='utf-8')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("이메일이 성공적으로 전송되었습니다.")
    except Exception as e:
        print(f"이메일 전송 실패: {e}")

tickers = ['AAPL', 'MSFT', 'GOOG', 'COIN', 'TSLA', 'AMZN']

report_body = "<h1>터틀 트레이딩 리포트</h1>"
report_body += "<table border='1'><tr><th>종목</th><th>신호</th><th>종가</th><th>ATR</th><th>손절가</th><th>목표가</th></tr>"

for ticker in tickers:
    signal, atr, stop_loss, target_price, last_close = get_turtle_signal(ticker)

    if signal == "BUY":
        report_body += f"<tr><td>{ticker}</td><td>{signal}</td><td>{last_close:.2f}</td><td>{atr:.2f}</td><td>{stop_loss:.2f}</td><td>{target_price:.2f}</td></tr>"
    else:
        report_body += f"<tr><td>{ticker}</td><td>{signal}</td><td>{last_close:.2f}</td><td>{atr:.2f}</td><td>N/A</td><td>N/A</td></tr>"

report_body += "</table>"

email_subject = "오늘의 터틀 트레이딩 리포트"
send_email(email_subject, report_body)
