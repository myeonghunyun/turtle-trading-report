import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
from email.mime.text import MIMEText
import sys
import talib
import os

# ----------------- 설정값 -----------------
TOTAL_SEED_KRW = 100000000
MAX_LOSS_RATE = 0.01
EXCHANGE_RATE_KRW_USD = 1361
# ------------------------------------------

def get_index_tickers(index_name):
    if index_name == 'sp500':
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        col_name = 'Symbol'
    elif index_name == 'nasdaq100':
        url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        col_name = 'Ticker'
    else:
        print(f"Unsupported index name: {index_name}", file=sys.stderr)
        return []
    
    try:
        print(f"{index_name} 지수 종목 목록을 가져오는 중...")
        tables = pd.read_html(url)
        for table in tables:
            if col_name in table.columns:
                tickers = table[col_name].tolist()
                tickers = [ticker.replace('.', '-') for ticker in tickers if isinstance(ticker, str) and not ticker.startswith('test')]
                return tickers
        print(f"Could not find ticker column '{col_name}' on the page.", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error fetching tickers for {index_name} from Wikipedia: {e}", file=sys.stderr)
        return []

def get_turtle_signal(ticker_data, vix_value, volume_threshold=1.5):
    try:
        ticker_data = ticker_data.dropna()
        if ticker_data.empty or len(ticker_data) < 200:
            return "데이터 부족", {}

        high_arr = ticker_data['High'].values
        low_arr = ticker_data['Low'].values
        close_arr = ticker_data['Close'].values
        volume_arr = ticker_data['Volume'].values

        # TA-Lib을 사용한 지표 계산
        atr = talib.ATR(high_arr, low_arr, close_arr, timeperiod=20)
        adx = talib.ADX(high_arr, low_arr, close_arr, timeperiod=14)
        ma200 = talib.MA(close_arr, timeperiod=200)
        plus_di = talib.PLUS_DI(high_arr, low_arr, close_arr, timeperiod=14)
        minus_di = talib.MINUS_DI(high_arr, low_arr, close_arr, timeperiod=14)

        # 20일 신고가 및 10일 신저가
        high_20d_shifted = ticker_data['High'].shift(1).rolling(window=20).max()
        low_10d_shifted = ticker_data['Low'].shift(1).rolling(window=10).min()

        last_close = ticker_data['Close'].iloc[-1]
        last_volume = ticker_data['Volume'].iloc[-1]
        last_atr = atr[-1]
        last_adx = adx[-1]
        last_ma200 = ma200[-1]
        last_plus_di = plus_di[-1]
        last_minus_di = minus_di[-1]
        last_20_high_prev = high_20d_shifted.iloc[-1]
        last_10_low_prev = low_10d_shifted.iloc[-1]

        avg_volume_20d = ticker_data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = last_volume / avg_volume_20d if avg_volume_20d > 0 else 0
        
        disparity_rate = (last_close - last_ma200) / last_ma200 * 100 if last_ma200 > 0 else 0
        atr_ratio = (last_atr / last_close) * 100 if last_close > 0 else 0

        signal = "보유"
        indicators = {
            "종가": last_close, "ATR": last_atr, "ATR비율": atr_ratio,
            "MA200": last_ma200, "괴리율": disparity_rate, "ADX": last_adx,
            "+DI": last_plus_di, "-DI": last_minus_di,
            "거래량비율": volume_ratio, "손절가": "N/A", "목표가": "N/A", "매수가능수량": 0
        }

        buy_condition = (
            last_close > last_20_high_prev and
            last_close > last_ma200 and
            vix_value < 30 and
            last_adx > 20 and
            volume_ratio > volume_threshold
        )
        if buy_condition:
            signal = "BUY"
            max_loss_usd = (TOTAL_SEED_KRW * MAX_LOSS_RATE) / EXCHANGE_RATE_KRW_USD
            loss_per_share = last_atr * 2
            if loss_per_share > 0:
                buy_quantity = int(max_loss_usd / loss_per_share)
                indicators["매수가능수량"] = buy_quantity
            else:
                indicators["매수가능수량"] = 0
            
            indicators["손절가"] = last_close - (2 * last_atr)
            indicators["목표가"] = last_close + (2 * last_atr)

        elif last_close < last_10_low_prev or last_close < last_ma200 or last_adx < 20:
             signal = "SELL"
        
        return signal, indicators
    except Exception as e:
        print(f"Error analyzing ticker data: {e}", file=sys.stderr)
        return "오류", {}

def send_email(subject, body):
    sender_email = "YOUR_EMAIL@gmail.com"
    sender_password = "YOUR_APP_PASSWORD"
    receiver_email = "RECEIVER_EMAIL@example.com"
    
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
        print(f"이메일 전송 실패: {e}", file=sys.stderr)

if __name__ == '__main__':
    print("스크립트 실행 시작...")
    
    sp500_tickers = get_index_tickers('sp500')
    nasdaq100_tickers = get_index_tickers('nasdaq100')
    
    try:
        vix_data = yf.download('^VIX', period="1d", auto_adjust=True, progress=False)
        vix_value = vix_data['Close'].iloc[-1].item() if not vix_data.empty else 0
    except Exception as e:
        print(f"VIX 데이터 가져오기 실패: {e}", file=sys.stderr)
        vix_value = 0
    
    all_tickers = list(set(sp500_tickers + nasdaq100_tickers))

    print(f"총 {len(all_tickers)}개 종목 데이터를 다운로드 중...")
    try:
        all_data = yf.download(all_tickers, period="1y", auto_adjust=True, progress=True)
    except Exception as e:
        print(f"데이터 다운로드 실패: {e}", file=sys.stderr)
        sys.exit(1)

    report_body = "<h1>터틀 트레이딩 리포트</h1>"
    report_body += (
        "<p>안녕하세요. 터틀 트레이더가 되기 위한 첫 리포트입니다. <br/>"
        "아래는 오늘 시장의 핵심 지표와 분석 결과입니다. 차근차근 확인해 보세요!</p>"
    )
    report_body += f"<p><b>VIX (공포 지수): {vix_value:.2f}</b> (20 이하: 안정, 30 이상: 경계)</p>"
    report_body += (
        "<p><b>지표 설명:</b><br/>"
        "• **ATR 비율:** 주식 가격 대비 변동성이 얼마나 큰지 알려주는 지표입니다. 비율이 높을수록 가격 변동이 심합니다.<br/>"
        "• **MA200 (200일 이동평균선):** 주식의 장기 추세를 나타냅니다. 현재가가 이 선 위에 있으면 상승 추세로 봅니다.<br/>"
        "• **괴리율:** 현재가가 MA200에서 얼마나 떨어져 있는지 보여주는 지표입니다.<br/>"
        "• **ADX:** 추세의 강도를 나타냅니다. 20 이상이면 추세가 강하다고 판단합니다. ADX가 상승하면 추세가 강해지고, 하락하면 추세가 약해집니다.<br/>"
        "• **+DI와 -DI:** 추세의 방향을 나타냅니다. +DI가 높으면 상승 추세, -DI가 높으면 하락 추세입니다.<br/>"
        "• **매수 가능 수량:** '시드 1억, 1% 손실 허용'이라는 규칙에 따라 계산된 수량입니다. 한 번의 거래에서 1백만 원 이상 손실을 보지 않도록 수량을 조절합니다.<br/>"
        "• **매도 신호:** <br/>"
        "  1. **'추세 약화'**: ADX 지표가 20 이하로 떨어져 추세가 약해졌다고 판단했을 때의 매도 신호입니다.<br/>"
        "  2. **'장기 추세 이탈'**: 주가가 200일 이동평균선 아래로 떨어졌을 때의 매도 신호입니다.<br/>"
        "  3. **'손절가'**: 주가가 10일 최저가를 하회했을 때의 매도 신호입니다. 이 경우 빠르게 손실을 끊어야 합니다."
        "</p>"
    )
    report_body += f"<p><b>자금 관리 원칙 (시드 {TOTAL_SEED_KRW:,}원):</b> 최대 손실 {TOTAL_SEED_KRW * MAX_LOSS_RATE:,}원 허용. 환율 {EXCHANGE_RATE_KRW_USD}원/달러</p>"

    def generate_html_section(ticker_list, index_name):
        buy_signals_html = ""
        sell_signals_html = ""
        
        for ticker in ticker_list:
            if ticker in all_data.columns:
                ticker_data_full = all_data.xs(ticker, axis=1, level=1)
                signal, indicators = get_turtle_signal(ticker_data_full, vix_value, volume_threshold=1.5)
                
                if signal == "오류":
                    print(f"⚠️ {ticker} 분석 중 오류: {indicators}", file=sys.stderr)
                    continue

                if signal == "BUY":
                    buy_signals_html += (
                        f"<li>{ticker}: 매수 (현재가 ${indicators['종가']:.2f}, ATR: ${indicators['ATR']:.2f}, ATR비율: {indicators['ATR비율']:.2f}%)"
                        f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; (MA200: ${indicators['MA200']:.2f}, 괴리율: {indicators['괴리율']:.2f}%, ADX: {indicators['ADX']:.2f}, +DI: {indicators['+DI']:.2f}, -DI: {indicators['-DI']:.2f})"
                        f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>매수 가능 수량: {indicators['매수가능수량']:,}개</b>, 목표가: ${indicators['목표가']:.2f}, 손절가: ${indicators['손절가']:.2f})</li>"
                    )
                elif signal == "SELL":
                    sell_signals_html += (
                        f"<li>{ticker}: 매도 (현재가 ${indicators['종가']:.2f}, ATR: ${indicators['ATR']:.2f}, ATR비율: {indicators['ATR비율']:.2f}%)"
                        f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; (MA200: ${indicators['MA200']:.2f}, 괴리율: {indicators['괴리율']:.2f}%, ADX: {indicators['ADX']:.2f}, +DI: {indicators['+DI']:.2f}, -DI: {indicators['-DI']:.2f})"
                        f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 매도 신호 발생)</li>"
                    )
        
        html_output = f"<h2>[{index_name}: 총 {len(ticker_list)}개]</h2>"
        html_output += "<h3>● BUY 신호:</h3><ul>" + (buy_signals_html if buy_signals_html else "<li>신호 없음</li>") + "</ul>"
        html_output += "<h3>● SELL 신호:</h3><ul>" + (sell_signals_html if sell_signals_html else "<li>신호 없음</li>") + "</ul>"
        
        return html_output

    report_body += generate_html_section(sp500_tickers, "S&P 500")
    report_body += generate_html_section(nasdaq100_tickers, "NASDAQ 100")

    email_subject = "오늘의 터틀 트레이딩 리포트 (S&P 500 & NASDAQ 100)"
    send_email(email_subject, report_body)
