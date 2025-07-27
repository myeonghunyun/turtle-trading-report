# main.py
# 리처드 덴킨의 터틀 트레이딩 리포트 시스템 (최종 완성형)
# 자동 리포트 생성 + 이메일 전송 (GitHub Actions 연동용)

import yfinance as yf
import pandas as pd
import datetime
import smtplib
import time  # ⏸️ 요청 간격 조절용
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import EMAIL_ADDRESS, EMAIL_PASSWORD, RECEIVER_EMAIL

# === 설정: 테스트용으로 종목 줄임 ===
TICKERS = ["C", "JPM"]  # 나중에 늘릴 수 있음

# 오늘 날짜
today = datetime.datetime.now().strftime("%Y-%m-%d")
usd_krw = 1370.00  # 실시간 환율 가정

# === VIX 가져오기 ===
def get_vix():
    try:
        vix = yf.Ticker("^VIX")
        data = vix.history(period="1d")
        return round(data['Close'][0], 2)
    except Exception as e:
        print(f"❌ VIX 가져오기 실패: {e}")
        return 16.32

# === ADX/DI 계산 함수 ===
def calculate_adx(high, low, close, window=14):
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window).mean()

    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    minus_dm = abs(minus_dm)

    plus_di = 100 * (plus_dm.ewm(alpha=1/window).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/window).mean() / atr)
    
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/window).mean()

    return round(adx.iloc[-1], 2), round(plus_di.iloc[-1], 2), round(minus_di.iloc[-1], 2)

# === 터틀 신호 계산 ===
def get_turtle_signal(ticker):
    time.sleep(0.6)  # ⏸️ Yahoo Finance 요청 제한 회피 (0.6초 대기)
    try:
        data = yf.download(ticker, period="60d", interval="1d")
        if len(data) < 20:
            print(f"⚠️ {ticker}: 데이터 부족")
            return None

        high_20 = data['High'][-21:-1].max()
        low_20 = data['Low'][-21:-1].min()
        close = data['Close'][-1]
        volume = data['Volume'][-1]

        recent = data[-14:]
        tr1 = recent['High'] - recent['Low']
        tr2 = abs(recent['High'] - recent['Close'].shift(1))
        tr3 = abs(recent['Low'] - recent['Close'].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.mean()
        atr_ratio = (atr / close) * 100

        stop_price = close - 2 * atr
        target_price = close + 2 * atr

        buy_signal = close > high_20
        sell_signal = close < low_20

        adx, plus_di, minus_di = calculate_adx(data['High'], data['Low'], data['Close'])

        return {
            'price': round(close, 2),
            'volume': volume,
            'atr_ratio': round(atr_ratio, 2),
            'buy': buy_signal,
            'sell': sell_signal,
            'target': round(target_price, 2) if buy_signal else None,
            'stop': round(stop_price, 2) if buy_signal else None,
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di
        }
    except Exception as e:
        print(f"❌ {ticker} 처리 중 오류: {str(e)}")
        return None

# === 리스크 기반 수량 계산 (시드 1억 기준) ===
def calculate_position_size(entry_price, stop_price, krw_rate=1370):
    entry_krw = entry_price * krw_rate
    stop_krw = stop_price * krw_rate
    risk_per_share = entry_krw - stop_krw  # 1주당 리스크 (원)
    
    max_risk_won = 1_000_000  # 1% 리스크 = 100만원
    if risk_per_share <= 0:
        return 0
    qty = int(max_risk_won / risk_per_share)
    return min(qty, 10000)  # 최대 1만 주 제한

# === 리포트 생성 ===
def generate_report():
    vix = get_vix()
    is_vix_safe = vix < 30

    report_lines = []
    report_lines.append("=== 환율 & 시장 상태 ===")
    report_lines.append(f"1 USD = {usd_krw:,.2f} KRW")
    report_lines.append(f"VIX (공포 지수): {vix} → {'✅ 안정' if is_vix_safe else '❌ 경계'} (30 미만: 매수 가능)")
    report_lines.append(f"ATR 기준: 1~3% 양호, 3% 이상 고변동성")
    report_lines.append("")
    report_lines.append("=== 터틀 트레이딩 리포트 (실전형) ===")
    report_lines.append(f"[시드 기준: 1억원 | 1% 리스크 = 1,000,000원]")

    buy_list = []
    sell_list = []
    weak_trend_list = []

    for ticker in TICKERS:
        sig = get_turtle_signal(ticker)
        if sig is None:
            continue

        won_price = int(sig['price'] * usd_krw)
        volume_krw = int(sig['volume'] * sig['price'] * usd_krw / 1e8)  # 억원 단위

        if sig['buy'] and is_vix_safe:
            qty = calculate_position_size(sig['price'], sig['stop'], usd_krw)
            buy_list.append((ticker, sig, won_price, volume_krw, qty))
        elif sig['sell']:
            sell_list.append((ticker, sig, won_price, volume_krw))
        
        if sig['adx'] < 20:
            weak_trend_list.append((ticker, sig['adx']))

    # ● BUY 신호 출력
    report_lines.append("● BUY 신호:")
    if buy_list:
        for ticker, sig, won_price, vol_krw, qty in buy_list:
            report_lines.append(f"   {ticker}: 매수 (현재가 {won_price:,}원, 거래량 {vol_krw:,}억원, "
                               f"ATR비율 {sig['atr_ratio']}%)")
            report_lines.append(f"     → 추세 강도: ADX {sig['adx']:.2f} (+DI {sig['plus_di']:.2f}, -DI {sig['minus_di']:.2f})")
            report_lines.append(f"     → 손절가: {int(sig['stop'] * usd_krw):,}원 | 목표가: {int(sig['target'] * usd_krw):,}원")
            report_lines.append(f"     → 추천 수량: {qty:,}주 (1% 리스크 기준)")
    else:
        report_lines.append("   (현재 VIX가 높거나, 신호 없음)")

    # ● SELL 신호 출력
    report_lines.append("● SELL 신호:")
    if sell_list:
        for ticker, sig, won_price, vol_krw in sell_list:
            report_lines.append(f"   {ticker}: 매도 (현재가 {won_price:,}원, 거래량 {vol_krw:,}억원, ATR비율 {sig['atr_ratio']}%)")
    else:
        report_lines.append("   (청산 대상 없음)")

    # ● 청산 권고 (추세 약화, ADX < 20)
    report_lines.append("● 청산 권고 (추세 약화, ADX < 20):")
    if weak_trend_list:
        for ticker, adx in weak_trend_list:
            report_lines.append(f"   {ticker}: ADX {adx:.2f} → 과감한 매도 권고")
    else:
        report_lines.append("   (현재 없음)")

    report_lines.append("")
    report_lines.append("=== 리포트 종료 ===")
    return "\n".join(report_lines)

# === 이메일 전송 ===
def send_email(report):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"[터틀 리포트] {today} - 추세 신호 업데이트"

    msg.attach(MIMEText(report, 'plain', 'utf-8'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, RECEIVER_EMAIL, text)
        server.quit()
        print("✅ 이메일 전송 성공!")
    except smtplib.SMTPAuthenticationError:
        print("❌ 이메일 전송 실패: 인증 오류. config.py의 이메일 주소와 앱 비밀번호 확인하세요.")
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {str(e)}")

# === 실행 ===
if __name__ == "__main__":
    print("🐢 터틀 리포트 생성 시작...")
    report = generate_report()
    print(report)
    send_email(report)