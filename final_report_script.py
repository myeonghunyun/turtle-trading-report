import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
from email.mime.text import MIMEText
import pandas_ta as ta  # ✅ talib 대신 pandas-ta 사용

# ----------------- 설정값 -----------------
TOTAL_SEED_KRW = 100000000  # 총 자금 1억 원
MAX_LOSS_RATE = 0.01        # 최대 손실 비율 1%
EXCHANGE_RATE_KRW_USD = 1372.88  # 환율
VOLUME_THRESHOLD = 1.2      # 거래량 비율 기준
ADX_THRESHOLD = 19          # ADX > 19면 추세 강함
# ------------------------------------------

def get_index_tickers(index_name):
    if index_name == 'sp500':
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        possible_cols = ['Symbol', 'Ticker symbol', 'Ticker']
    elif index_name == 'nasdaq100':
        url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        possible_cols = ['Ticker', 'Ticker symbol', 'Company']
    else:
        return []

    try:
        tables = pd.read_html(url)
        for table in tables:
            for col in possible_cols:
                if col in table.columns:
                    tickers = table[col].dropna().astype(str).tolist()
                    tickers = [t.strip() for t in tickers if isinstance(t, str) and len(t) <= 10 and t != 'nan']
                    tickers = [t.replace('.', '-') for t in tickers]
                    return tickers
        return []
    except Exception as e:
        print(f"❌ {index_name} 티커 추출 실패: {e}")
        return []


def get_turtle_signal(ticker_data, vix_value):
    try:
        ticker_data = ticker_data.ffill().dropna()
        if ticker_data.empty or len(ticker_data) < 200:
            return "데이터 부족", {}

        # pandas-ta로 지표 계산
        ticker_data['ATR'] = ta.atr(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=20)
        adx_series = ta.adx(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=14)
        if adx_series is not None and not adx_series.empty:
            ticker_data['ADX'] = adx_series['ADX_14']
            ticker_data['+DI'] = adx_series['DMP_14']
            ticker_data['-DI'] = adx_series['DMN_14']
        ticker_data['MA200'] = ta.sma(ticker_data['Close'], length=200)

        # 마지막 값 추출
        last_row = ticker_data.iloc[-1]
        if last_row.isnull().any():
            return "분석 오류", {}

        last_close = last_row['Close']
        last_volume = ticker_data['Volume'].iloc[-1]
        last_atr = last_row['ATR']
        last_adx = last_row['ADX'] if pd.notna(last_row['ADX']) else 0
        last_plus_di = last_row['+DI'] if pd.notna(last_row['+DI']) else 0
        last_minus_di = last_row['-DI'] if pd.notna(last_row['-DI']) else 0
        last_ma200 = last_row['MA200'] if pd.notna(last_row['MA200']) else 0

        # 20일 신고가 (어제 기준)
        last_20_high_prev = ticker_data['High'].rolling(20).max().iloc[-2] if len(ticker_data) >= 21 else last_close
        # 10일 저가 (오늘 기준)
        last_10_low = ticker_data['Low'].rolling(10).min().iloc[-1] if len(ticker_data) >= 10 else last_close

        # 평균 거래량 (20일)
        avg_volume_20d = ticker_data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = last_volume / avg_volume_20d if avg_volume_20d > 0 else 0

        # 괴리율 & ATR비율
        disparity_rate = (last_close - last_ma200) / last_ma200 * 100 if last_ma200 > 0 else 0
        atr_ratio = (last_atr / last_close) * 100 if last_close > 0 else 0

        # 원화 변환
        close_krw = round(last_close * EXCHANGE_RATE_KRW_USD, 0)
        target_price_krw = round((last_close + 2 * last_atr) * EXCHANGE_RATE_KRW_USD, 0)
        stop_price_krw = round((last_close - 2 * last_atr) * EXCHANGE_RATE_KRW_USD, 0)
        volume_krw_billion = (last_volume * last_close * EXCHANGE_RATE_KRW_USD) / 1e8  # 억원

        # 수량 계산
        max_loss_usd = (TOTAL_SEED_KRW * MAX_LOSS_RATE) / EXCHANGE_RATE_KRW_USD
        loss_per_share = last_atr * 2
        buy_quantity = int(max_loss_usd / loss_per_share) if loss_per_share > 0 else 0

        indicators = {
            "종가": last_close,
            "종가_krw": close_krw,
            "거래량_krw_billion": volume_krw_billion,
            "ATR": last_atr,
            "ATR비율": atr_ratio,
            "MA200": last_ma200,
            "괴리율": disparity_rate,
            "ADX": last_adx,
            "+DI": last_plus_di,
            "-DI": last_minus_di,
            "거래량비율": volume_ratio,
            "손절가": stop_price_krw,
            "목표가": target_price_krw,
            "매수가능수량": buy_quantity,
            "signal_strength": 0
        }

        is_above_ma200 = last_close > last_ma200

        # 매수 조건
        buy_condition = (
            last_close > last_20_high_prev and
            is_above_ma200 and
            vix_value < 30 and
            last_adx > ADX_THRESHOLD and
            volume_ratio > VOLUME_THRESHOLD
        )

        if buy_condition:
            signal = "BUY"
            indicators["signal_strength"] = last_adx - atr_ratio
        elif not is_above_ma200 or last_adx < ADX_THRESHOLD or last_close < last_10_low:
            signal = "SELL"
            indicators["signal_strength"] = -last_adx
        else:
            signal = "보유"
            indicators["signal_strength"] = 0

        return signal, indicators

    except Exception as e:
        print(f"❌ 분석 중 오류: {e}")
        return "오류", {}


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
        print("✅ 이메일이 성공적으로 전송되었습니다.")
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {e}")


# ================ 메인 실행 ==================
if __name__ == '__main__':
    print("🚀 터틀 트레이딩 리포트 시작...")

    sp500_tickers = get_index_tickers('sp500')
    nasdaq100_tickers = get_index_tickers('nasdaq100')
    all_tickers = list(set(sp500_tickers + nasdaq100_tickers))
    print(f"✅ {len(all_tickers)}개 티커 로드 완료")

    # VIX 가져오기
    vix_data = yf.download('^VIX', period="5d", auto_adjust=True)
    if vix_data.empty or vix_data['Close'].dropna().empty:
        vix_value = 30.0
    else:
        vix_value = float(vix_data['Close'].dropna().iloc[-1])
    print(f"📈 VIX 값: {vix_value:.2f}")

    # 데이터 다운로드
    print(f"📊 {len(all_tickers)}개 종목 데이터 다운로드 중...")
    try:
        data = yf.download(all_tickers, period="1y", auto_adjust=True, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(1)
    except Exception as e:
        print(f"❌ 데이터 다운로드 실패: {e}")
        exit()

    # A++ 종목 선별
    a_plus_plus_list = []

    def is_a_plus_plus(ind):
        return (
            ind['ADX'] > 25 and
            ind['+DI'] > ind['-DI'] and
            ind['종가'] > ind['MA200'] and
            1.5 <= ind['ATR비율'] <= 3.5 and
            ind['거래량비율'] > 1.5 and
            ind['매수가능수량'] > 0
        )

    for ticker in all_tickers:
        try:
            if ticker not in data.columns:
                continue
            price_data = data[[ticker]].dropna()
            if len(price_data) < 200:
                continue
            price_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            signal, ind = get_turtle_signal(price_data, vix_value)
            if signal == "BUY" and is_a_plus_plus(ind):
                a_plus_plus_list.append({
                    'ticker': ticker,
                    'close_krw': ind['종가_krw'],
                    'volume_krw': ind['거래량_krw_billion'],
                    'atr_ratio': ind['ATR비율'],
                    'target_krw': ind['목표가'],
                    'stop_krw': ind['손절가'],
                    'quantity': ind['매수가능수량'],
                    'volume_ratio': ind['거래량비율']
                })
        except Exception as e:
            continue

    # A++ 종목을 ATR비율 낮은 순으로 정렬
    a_plus_plus_list = sorted(a_plus_plus_list, key=lambda x: x['atr_ratio'])

    def format_krw(amount):
        return f"{amount:,.0f}만원" if amount < 10000 else f"{amount / 10000:,.1f}억원"

    def format_price(price):
        return f"{price:,.0f}만원"

    # 리포트 본문 생성
    report_body = f"""
    <h1>🐢 터틀 트레이딩 리포트</h1>
    <p>안녕하세요. 오늘의 터틀 트레이딩 신호입니다.</p>
    <p><b>VIX (공포 지수): {vix_value:.2f}</b> (20 이하: 안정, 30 이상: 경계)</p>
    <p><b>자금 원칙:</b> 시드 {TOTAL_SEED_KRW:,}원, 최대 손실 {int(TOTAL_SEED_KRW * MAX_LOSS_RATE):,}원, 환율 {EXCHANGE_RATE_KRW_USD:,.2f}원/달러</p>
    
    <h2>📌 지표 설명</h2>
    <ul>
        <li><b>ATR 비율:</b> 주식 가격 대비 변동성이 얼마나 큰지 알려주는 지표입니다. 비율이 높을수록 가격 변동이 심합니다.</li>
        <li><b>MA200 (200일 이동평균선):</b> 주식의 장기 추세를 나타냅니다. 현재가가 이 선 위에 있으면 상승 추세로 봅니다.</li>
        <li><b>괴리율:</b> 현재가가 MA200에서 얼마나 떨어져 있는지 보여주는 지표입니다.</li>
        <li><b>ADX:</b> 추세의 강도를 나타냅니다. 20 이상이면 추세가 강하다고 판단합니다.</li>
        <li><b>매수 가능 수량:</b> '시드 1억, 1% 손실 허용' 규칙에 따라 계산된 수량입니다.</li>
        <li><b>매도 신호:</b><br/>
            1. <b>추세 약화:</b> ADX 지표가 20 이하로 떨어짐<br/>
            2. <b>장기 추세 이탈:</b> 주가가 200일 이동평균선 아래로 떨어짐<br/>
            3. <b>손절가:</b> 주가가 10일 최저가를 하회할 때
        </li>
    </ul>

    <h2>=== 환율 & ATR 가이드 ===</h2>
    <pre>
1 USD = {EXCHANGE_RATE_KRW_USD:,.2f} KRW
ATR 비율 1~3% 양호, 3% 이상 고변동성
    </pre>
    """

    # ✅ 실전 거래량 비율 판단 가이드 추가 (A++ 전에 위치)
    report_body += """
    <h2>📌 실전 거래량 비율 판단 가이드</h2>
    <p><b>거래량비율</b>은 "오늘 거래량이 평소보다 몇 배 늘었는가?"를 보여줍니다.<br/>
    이 수치는 시장의 관심과 변동성의 전조를 파악하는 핵심 지표입니다.</p>
    
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; font-size: 14px;">
        <tr style="background-color: #f2f2f2;">
            <th>거래량비율</th>
            <th>시장 의미</th>
            <th>실전 판단</th>
        </tr>
        <tr>
            <td>< 1.0x</td>
            <td>거래 위축</td>
            <td>관심이 줄고 있음. 추세 약화 가능성 있음</td>
        </tr>
        <tr>
            <td>1.0~1.5x</td>
            <td>보통 수준</td>
            <td>특별한 움직임 없음. 보유 관찰</td>
        </tr>
        <tr>
            <td>1.5~2.0x</td>
            <td>주목 필요</td>
            <td>상승/하락 모멘텀 시작 가능성 ↑</td>
        </tr>
        <tr>
            <td>> 2.0x</td>
            <td>강한 관심</td>
            <td>급등/급락 전조. 진입 또는 이탈 고려</td>
        </tr>
        <tr>
            <td>> 3.0x</td>
            <td>폭발적 관심</td>
            <td>뉴스, 실적 발표 등 외부 요인 가능성 높음</td>
        </tr>
    </table>
    <p><b>💡 팁:</b> A++ 종목은 <b>거래량비율 > 1.5x</b>를 충족해야 합니다.</p>
    """

    # ✅ A++ 종목 섹션 추가 (실전 가이드 다음에 위치)
    if a_plus_plus_list:
        report_body += "<h2>🌟 나만의 A++ 추천 종목 (고성과 + 안정성)</h2><ul>"
        for s in a_plus_plus_list:
            report_body += f"""
            <li><b>{s['ticker']}</b>: A++ 종목 (종가 {format_price(s['close_krw'])}, 
            거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x, ATR비율 {s['atr_ratio']:.2f}%,
            목표가 {format_price(s['target_krw'])}, 손절가 {format_price(s['stop_krw'])})
            → <b>매수 가능 수량: {s['quantity']:,}주</b></li>
            """
        report_body += "</ul><hr><br/>"
    else:
        report_body += "<h2>🌟 나만의 A++ 추천 종목</h2><p>현재 기준에 맞는 A++ 종목이 없습니다.</p><hr><br/>"

    # 섹션 생성 함수 (매수/매도 수 포함)
    def generate_section(ticker_list, name):
        buy_signals = []
        sell_signals = []

        for ticker in ticker_list:
            try:
                if ticker not in data.columns:
                    continue
                price_data = data[[ticker]].dropna()
                if len(price_data) < 200:
                    continue
                price_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                signal, ind = get_turtle_signal(price_data, vix_value)

                if signal == "BUY":
                    buy_signals.append({
                        'ticker': ticker,
                        'close_krw': ind['종가_krw'],
                        'volume_krw': ind['거래량_krw_billion'],
                        'atr_ratio': ind['ATR비율'],
                        'target_krw': ind['목표가'],
                        'stop_krw': ind['손절가'],
                        'volume_ratio': ind['거래량비율']
                    })
                elif signal == "SELL":
                    sell_signals.append({
                        'ticker': ticker,
                        'close_krw': ind['종가_krw'],
                        'volume_krw': ind['거래량_krw_billion'],
                        'atr_ratio': ind['ATR비율'],
                        'volume_ratio': ind['거래량비율']
                    })
            except:
                continue

        buy_signals = sorted(buy_signals, key=lambda x: x['atr_ratio'])
        sell_signals = sorted(sell_signals, key=lambda x: x['atr_ratio'])

        section = f"<h2>[{name}: 티커 {len(ticker_list)}개, 매수 {len(buy_signals)}개, 매도 {len(sell_signals)}개]</h2>"

        buy_html = ""
        for s in buy_signals:
            buy_html += f"""
            <li><b>{s['ticker']}</b>: 매수 
                (종가 {format_price(s['close_krw'])}, 거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x, 
                ATR비율 {s['atr_ratio']:.2f}%, 목표가 {format_price(s['target_krw'])}, 손절가 {format_price(s['stop_krw'])})
            </li>
            """

        sell_html = ""
        for s in sell_signals:
            sell_html += f"""
            <li><b>{s['ticker']}</b>: 매도 
                (종가 {format_price(s['close_krw'])}, 거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x, 
                ATR비율 {s['atr_ratio']:.2f}%)
            </li>
            """

        return section + \
               "<h3>🟢 BUY 신호</h3><ul>" + (buy_html if buy_html else "<li>없음</li>") + "</ul>" + \
               "<h3>🔴 SELL 신호</h3><ul>" + (sell_html if sell_html else "<li>없음</li>") + "</ul>"

    report_body += generate_section(sp500_tickers, "S&P500")
    report_body += generate_section(nasdaq100_tickers, "NASDAQ100")

    subject = f"📈 터틀 트레이딩 리포트 (VIX: {vix_value:.1f})"
    send_email(subject, report_body)

    print("✅ 리포트 생성 및 전송 완료!")
