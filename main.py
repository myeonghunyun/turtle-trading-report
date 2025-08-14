# main.py
import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
import pandas_ta as ta
import os
import time
from curl_cffi import requests as curl_requests
import sys
import io

# ----------------- 설정값 -----------------
TOTAL_SEED_KRW = 100000000  # 총 자금 1억 원
MAX_LOSS_RATE = 0.01        # 최대 손실 비율 1%
VOLUME_THRESHOLD = 1.2      # 거래량 비율 기준
ADX_THRESHOLD = 19          # ADX > 19면 추세 강함
# ------------------------------------------

def get_index_tickers(index_name):
    """Wikipedia에서 S&P 500 또는 Nasdaq-100 티커 목록을 가져옵니다."""
    if index_name == 'sp500':
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        possible_cols = ['Symbol', 'Ticker symbol', 'Ticker']
    elif index_name == 'nasdaq100':
        url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        possible_cols = ['Ticker', 'Ticker symbol', 'Company']
    else:
        print(f"❌ 지원하지 않는 인덱스: {index_name}")
        return []

    try:
        html_content = curl_requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text
        tables = pd.read_html(io.StringIO(html_content))
        for table in tables:
            for col in possible_cols:
                if col in table.columns:
                    tickers = table[col].dropna().astype(str).tolist()
                    tickers = [t.strip() for t in tickers if isinstance(t, str) and 1 <= len(t) <= 10 and t != 'nan']
                    tickers = [t.replace('.', '-') for t in tickers]
                    print(f"✅ {index_name} 티커 {len(tickers)}개 로드 완료.")
                    return tickers
        print(f"❌ {index_name} 티커를 찾을 수 없습니다.")
        return []
    except Exception as e:
        print(f"❌ {index_name} 티커 추출 실패: {e}")
        return []

def get_turtle_signal(ticker, ticker_data, vix_value, exchange_rate):
    """단일 종목에 대한 터틀 트레이딩 신호를 계산합니다."""
    try:
        if not isinstance(ticker_data, pd.DataFrame) or ticker_data.empty:
            return "데이터 없음", {}

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
        ticker_data['RSI'] = ta.rsi(ticker_data['Close'], length=14) # RSI 추가

        if ticker_data.iloc[-1].isnull().any():
            return "분석 오류", {}

        last_row = ticker_data.iloc[-1]
        last_close = last_row['Close']
        last_volume = last_row['Volume']
        last_atr = last_row['ATR']
        last_adx = last_row['ADX'] if pd.notna(last_row['ADX']) else 0
        last_plus_di = last_row['+DI'] if pd.notna(last_row['+DI']) else 0
        last_minus_di = last_row['-DI'] if pd.notna(last_row['-DI']) else 0
        last_ma200 = last_row['MA200'] if pd.notna(last_row['MA200']) else 0
        last_rsi = last_row['RSI'] if pd.notna(last_row['RSI']) else 0

        last_20_high_prev = ticker_data['High'].iloc[:-1].rolling(20).max().iloc[-1] if len(ticker_data) >= 21 else last_close
        last_10_low = ticker_data['Low'].rolling(10).min().iloc[-1] if len(ticker_data) >= 10 else last_close

        avg_volume_20d = ticker_data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = last_volume / avg_volume_20d if avg_volume_20d > 0 else 0

        disparity_rate = (last_close - last_ma200) / last_ma200 * 100 if last_ma200 > 0 else 0
        atr_ratio = (last_atr / last_close) * 100 if last_close > 0 else 0

        close_krw = round(last_close * exchange_rate, 0)
        target_price_krw = round((last_close + 2 * last_atr) * exchange_rate, 0)
        stop_price_krw = round((last_close - 2 * last_atr) * exchange_rate, 0)
        volume_krw_billion = (last_volume * last_close * exchange_rate) / 1e8

        max_loss_usd = (TOTAL_SEED_KRW * MAX_LOSS_RATE) / exchange_rate
        loss_per_share = last_atr * 2
        buy_quantity = int(max_loss_usd / loss_per_share) if loss_per_share > 0 else 0

        indicators = {
            "종가": last_close, "종가_krw": close_krw, "거래량_krw_billion": volume_krw_billion,
            "ATR": last_atr, "ATR비율": atr_ratio, "MA200": last_ma200, "괴리율": disparity_rate,
            "ADX": last_adx, "+DI": last_plus_di, "-DI": last_minus_di, "거래량비율": volume_ratio,
            "손절가": stop_price_krw, "목표가": target_price_krw, "매수가능수량": buy_quantity, "RSI": last_rsi
        }

        is_above_ma200 = last_close > last_ma200

        # 매수 조건 (RSI 과매수 제외 조건 추가)
        buy_condition = (
            last_close > last_20_high_prev and
            is_above_ma200 and
            vix_value < 30 and
            last_adx > ADX_THRESHOLD and
            volume_ratio > VOLUME_THRESHOLD and
            last_rsi < 70 # RSI가 과매수 상태가 아닐 때만 매수
        )

        if buy_condition:
            signal = "BUY"
        elif not is_above_ma200 or last_adx < ADX_THRESHOLD or last_close < last_10_low:
            signal = "SELL"
        else:
            signal = "보유"

        return signal, indicators

    except Exception as e:
        print(f"❌ {ticker} 분석 중 오류: {e}")
        return "오류", {}

def format_krw(amount):
    """금액을 '만원' 또는 '억원' 단위로 포맷팅합니다."""
    if amount >= 100000000:
        return f"{amount / 100000000:,.1f}억원"
    else:
        return f"{amount / 10000:,.0f}만원"

def send_email(subject, body):
    """리포트를 이메일로 전송합니다."""
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    receiver_email = os.getenv("RECEIVER_EMAIL")

    if not all([sender_email, sender_password, receiver_email]):
        print("❌ 이메일 설정이 누락되었습니다. Secrets를 확인하세요.")
        return

    body_clean = body.replace('\xa0', ' ').replace('\u00A0', ' ')
    msg = MIMEText(body_clean, 'html', _charset='utf-8')
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

# ================ 백테스팅 함수 추가 ==================
def backtest_strategy(ticker_data):
    """단순 백테스팅을 통해 전략의 수익률을 계산합니다."""
    if ticker_data.empty or len(ticker_data) < 250:
        return None

    signals = pd.DataFrame(index=ticker_data.index)
    signals['Close'] = ticker_data['Close']
    signals['Position'] = 0
    signals['Strategy'] = 1.0  # 초기 자산 1.0

    # 지표 계산
    signals['MA200'] = ta.sma(signals['Close'], length=200)
    signals['RSI'] = ta.rsi(signals['Close'], length=14)
    adx_series = ta.adx(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=14)
    if adx_series is not None and not adx_series.empty:
        signals['ADX'] = adx_series['ADX_14']
    signals['20D_High'] = ticker_data['High'].rolling(20).max()
    signals['10D_Low'] = ticker_data['Low'].rolling(10).min()

    # 백테스팅 루프
    for i in range(200, len(signals)):
        prev_close = signals['Close'].iloc[i-1]
        current_close = signals['Close'].iloc[i]

        buy_condition = (
            current_close > signals['20D_High'].iloc[i-1] and
            current_close > signals['MA200'].iloc[i] and
            signals['ADX'].iloc[i] > ADX_THRESHOLD and
            signals['RSI'].iloc[i] < 70
        )
        sell_condition = (
            current_close < signals['MA200'].iloc[i] or
            signals['ADX'].iloc[i] < ADX_THRESHOLD or
            current_close < signals['10D_Low'].iloc[i]
        )

        if buy_condition and signals['Position'].iloc[i-1] == 0:
            signals['Position'].iloc[i] = 1
        elif sell_condition and signals['Position'].iloc[i-1] == 1:
            signals['Position'].iloc[i] = 0
        else:
            signals['Position'].iloc[i] = signals['Position'].iloc[i-1]

        # 수익률 계산
        if signals['Position'].iloc[i-1] == 1:
            return_rate = (current_close / prev_close) - 1
            signals['Strategy'].iloc[i] = signals['Strategy'].iloc[i-1] * (1 + return_rate)
        else:
            signals['Strategy'].iloc[i] = signals['Strategy'].iloc[i-1]

    # 최종 수익률
    if not signals['Strategy'].empty:
        total_return = (signals['Strategy'].iloc[-1] - 1) * 100
        return total_return
    return None

# ================ 메인 실행 ==================
if __name__ == '__main__':
    print("🚀 터틀 트레이딩 리포트 시작...")
    REPORT_TYPE = os.getenv("REPORT_TYPE", "morning_plan")
    
    session = curl_requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    EXCHANGE_RATE_KRW_USD = 1372.88
    try:
        forex_data = yf.download("KRW=X", period="1d", auto_adjust=True, session=session, progress=False)
        if forex_data is not None and not forex_data.empty:
            EXCHANGE_RATE_KRW_USD = float(forex_data['Close'].iloc[-1])
        else:
            print("⚠️ 환율 데이터가 비어 있습니다. 기본값 사용")
    except Exception as e:
        print(f"⚠️ 환율 가져오기 실패: {e}, 기본값 사용")
    print(f"💱 실시간 환율: 1 USD = {EXCHANGE_RATE_KRW_USD:,.2f} KRW")

    vix_value = 30.0
    try:
        vix_data = yf.download('^VIX', period="5d", auto_adjust=True, session=session, progress=False)
        if vix_data is not None and not vix_data.empty and not vix_data['Close'].dropna().empty:
            vix_value = float(vix_data['Close'].dropna().iloc[-1])
        else:
            print("⚠️ VIX 데이터가 비어 있습니다. 기본값 사용")
    except Exception as e:
        print(f"⚠️ VIX 가져오기 실패: {e}, 기본값 사용")
    print(f"📈 VIX 값: {vix_value:.2f}")

    # ✅ S&P 500 전망 PER 동적으로 가져오기
    forward_pe = 22.4 # 기본값
    try:
        sp500_info = yf.Ticker('^GSPC').info
        if 'forwardPE' in sp500_info and sp500_info['forwardPE'] is not None:
            forward_pe = sp500_info['forwardPE']
            print(f"✅ S&P 500 전망 PER: {forward_pe:.1f}")
        else:
            print("⚠️ S&P 500 전망 PER 데이터 없음. 기본값 사용")
    except Exception as e:
        print(f"⚠️ S&P 500 전망 PER 가져오기 실패: {e}, 기본값 사용")

    sp500_tickers = get_index_tickers('sp500')
    nasdaq100_tickers = get_index_tickers('nasdaq100')
    all_tickers = list(set(sp500_tickers + nasdaq100_tickers))
    
    if not all_tickers:
        print("❌ 티커 목록이 비어 있습니다. 프로그램을 종료합니다.")
        sys.exit(1)

    data = {}
    failed_tickers = []
    print(f"📊 총 {len(all_tickers)}개 종목 데이터 다운로드 중...")
    
    for i, ticker in enumerate(all_tickers):
        print(f"({i+1}/{len(all_tickers)}) 다운로드 중: {ticker}")
        try:
            ticker_data = yf.download(ticker, period="1y", auto_adjust=True, session=session, progress=False)
            if ticker_data is not None and not ticker_data.empty and len(ticker_data) >= 200:
                data[ticker] = ticker_data
            else:
                failed_tickers.append(ticker)
        except Exception as e:
            print(f"❌ {ticker} 다운로드 실패: {e}")
            failed_tickers.append(ticker)
        
        time.sleep(1)

    print(f"✅ 성공: {len(data)}개, ❌ 실패: {len(failed_tickers)}개")

    a_plus_plus_list = []
    def is_a_plus_plus(ind):
        return (
            ind['ADX'] > 25 and
            ind['+DI'] > ind['-DI'] and
            ind['종가'] > ind['MA200'] and
            1.5 <= ind['ATR비율'] <= 3.5 and
            ind['거래량비율'] > 1.5 and
            ind['매수가능수량'] > 0 and
            ind['RSI'] < 70
        )
    
    for ticker, price_data in data.items():
        try:
            price_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            signal, ind = get_turtle_signal(ticker, price_data, vix_value, EXCHANGE_RATE_KRW_USD)
            if signal == "BUY" and is_a_plus_plus(ind):
                a_plus_plus_list.append({
                    'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'],
                    'volume_krw': ind['거래량_krw_billion'], 'atr_ratio': ind['ATR비율'],
                    'target': (ind['종가'] + 2 * ind['ATR']), 'stop': (ind['종가'] - 2 * ind['ATR']),
                    'target_krw': ind['목표가'], 'stop_krw': ind['손절가'],
                    'quantity': ind['매수가능수량'], 'volume_ratio': ind['거래량비율'], 'RSI': ind['RSI']
                })
        except Exception as e:
            print(f"⚠️ {ticker} A++ 분석 중 오류: {e}")
            continue

    a_plus_plus_list = sorted(a_plus_plus_list, key=lambda x: x['atr_ratio'])

    if REPORT_TYPE == "morning_plan":
        title = "🌅 [계획용] 오전 7시 터틀 트레이딩 리포트"
        subtitle = "장 마감 후, 어제 데이터 기반으로 작성된 <b>계획 수립용 리포트</b>입니다."
        timing_note = "📌 이 리포트는 어제 종가 기준입니다. 장 시작 전에 반드시 실시간 재검토하세요."
    else:
        title = "🌃 [실시간] 오후 10시 터틀 트레이딩 리포트"
        subtitle = "장 시작 직전, <b>프리마켓 실시간 데이터</b>를 반영한 <b>최종 결정용 리포트</b>입니다."
        timing_note = "📌 이 리포트는 프리마켓 가격을 반영했습니다. 매수 주문을 위한 최종 확인이 필요합니다."

    report_body = f"""
    <h1>{title}</h1>
    <p>{subtitle}</p>
    <p><b>VIX (공포 지수): {vix_value:.2f}</b> (20 이하: 안정, 30 이상: 경계)</p>
    <p><b>자금 원칙:</b> 시드 {TOTAL_SEED_KRW:,}원, 최대 손실 {int(TOTAL_SEED_KRW * MAX_LOSS_RATE):,}원, 환율 {EXCHANGE_RATE_KRW_USD:,.2f}원/달러</p>

    <h2>📌 지표 설명</h2>
    <ul>
        <li><b>RSI:</b> 주식의 과매수/과매도 상태를 보여주는 지표 (70 이상: 과매수, 30 이하: 과매도).</li>
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

    <p><b>{timing_note}</b></p>
    """

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

    # ✅ 시장 과열도 진단 섹션을 A++ 종목 섹션 앞으로 이동
    disparity_sp500 = 0
    try:
        sp500_data = yf.download('^GSPC', period="250d", auto_adjust=True, session=session, progress=False)
        if not sp500_data.empty and len(sp500_data) >= 200:
            sp500_close = sp500_data['Close'].iloc[-1]
            sp500_ma200 = sp500_data['Close'].rolling(200).mean().iloc[-1]
            if pd.notna(sp500_ma200) and sp500_ma200 > 0:
                disparity_sp500 = (sp500_close / sp500_ma200 - 1) * 100
        else:
            print("⚠️ S&P 500 데이터 부족 또는 비어 있음.")
    except Exception as e:
        print(f"⚠️ S&P 500 데이터 가져오기 실패: {e}")
        disparity_sp500 = 0

    atr_ratios = [ind['atr_ratio'] for ind in a_plus_plus_list if 'atr_ratio' in ind]
    avg_atr_ratio = sum(atr_ratios) / len(atr_ratios) if atr_ratios else 0
    
    market_condition_html = f"""
    <h2>⚠️ 시장 과열도 진단</h2>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; font-size: 14px;">
        <tr style="background-color: #f2f2f2;">
            <th>지표</th>
            <th>현재 값</th>
            <th>판단 기준</th>
            <th>의미</th>
        </tr>
        <tr>
            <td><b>VIX</b></td>
            <td>{vix_value:.2f}</td>
            <td>< 20: 안정<br>> 30: 공포</td>
            <td>{'🟢 안정' if vix_value < 20 else '🟠 경계' if vix_value < 30 else '🔴 공포'}</td>
        </tr>
        <tr>
            <td><b>S&P 500 괴리율</b></td>
            <td>{disparity_sp500:+.1f}%</td>
            <td>> +10%: 과열<br>< -10%: 저평가</td>
            <td>{'🔴 과열' if disparity_sp500 > 10 else '🟢 정상' if disparity_sp500 > -10 else '🔴 저평가'}</td>
        </tr>
        <tr>
            <td><b>ATR 평균</b></td>
            <td>{avg_atr_ratio:.2f}%</td>
            <td>1~3% 양호<br>> 3% 고변동성</td>
            <td>{'🟢 양호' if avg_atr_ratio < 3 else '🟠 고변동성'}</td>
        </tr>
        <tr>
            <td><b>전망 PER</b></td>
            <td>{forward_pe:.1f}배</td>
            <td>15~16: 평균<br>> 20: 고평가</td>
            <td>{'🔴 고평가' if forward_pe > 20 else '🟠 다소 높음' if forward_pe > 18 else '🟢 정상'}</td>
        </tr>
    </table>

    <h3>💡 시장 상황 종합 판단 및 행동 요령</h3>
    <ul>
    """

    if vix_value < 20 and disparity_sp500 > 10 and forward_pe > 20:
        market_condition_html += """
        <li><b>🔴 시장 과열 단계</b><br>
            → VIX 낮음, 지수 과열, 밸류에이션 높음<br>
            → <b>진입 규모를 1%에서 0.5%로 줄이세요</b><br>
            → OCO 주문 철저히 설정, 익절 빠르게 고려</li>
        """
    elif vix_value > 30 or disparity_sp500 < -10:
        market_condition_html += """
        <li><b>🟢 시장 저점 기회</b><br>
            → 공포 지수 높음, 지수 저평가<br>
            → <b>진입 규모 1% 유지 또는 1.5%로 확대 고려</b><br>
            → 강한 추세 종목 적극 진입</li>
        """
    elif avg_atr_ratio > 3.5:
        market_condition_html += """
        <li><b>🟠 고변동성 장세</b><br>
            → ATR 평균 3.5% 초과<br>
            → <b>손절가 엄격히 지키기</b><br>
            → 익절가 도달 시 빠르게 실현 고려</li>
        """
    else:
        market_condition_html += """
        <li><b>🟢 정상적 장세</b><br>
            → 모든 지표가 정상 범위<br>
            → <b>기존 1% 리스크 원칙 유지</b><br>
            → A++ 종목 중심으로 안정적 진입</li>
        """

    market_condition_html += """
    </ul>
    <p><i>📌 참고: 이 판단은 참고용이며, 최종 결정은 본인 책임입니다.</i></p>
    </div>
    """
    report_body += market_condition_html
    
    if a_plus_plus_list:
        report_body += "<h2>🌟 나만의 A++ 추천 종목 (고성과 + 안정성)</h2><ul>"
        for s in a_plus_plus_list:
            report_body += f"""
            <li><b>{s['ticker']}</b>: A++ 종목 (종가 ${s['close']:.2f} ({format_krw(s['close_krw'])}),
            거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x, ATR비율 {s['atr_ratio']:.2f}%,
            RSI {s['RSI']:.2f},
            목표가 ${s['target']:.2f} ({format_krw(s['target_krw'])}), 손절가 ${s['stop']:.2f} ({format_krw(s['stop_krw'])}))
            → <b>매수 가능 수량: {s['quantity']:,}주</b></li>
            """
        report_body += "</ul><hr><br/>"
    else:
        report_body += "<h2>🌟 나만의 A++ 추천 종목</h2><p>현재 기준에 맞는 A++ 종목이 없습니다.</p><hr><br/>"

    def generate_section(ticker_list, name):
        buy_signals = []
        sell_signals = []
        
        for ticker in ticker_list:
            if ticker not in data:
                continue
            
            try:
                price_data = data[ticker].copy()
                if len(price_data) < 200:
                    continue
                
                price_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                signal, ind = get_turtle_signal(ticker, price_data, vix_value, EXCHANGE_RATE_KRW_USD)
                
                if signal == "BUY":
                    buy_signals.append({
                        'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'],
                        'volume_krw': ind['거래량_krw_billion'], 'atr_ratio': ind['ATR비율'],
                        'target': (ind['종가'] + 2 * ind['ATR']), 'stop': (ind['종가'] - 2 * ind['ATR']),
                        'target_krw': ind['목표가'], 'stop_krw': ind['손절가'],
                        'volume_ratio': ind['거래량비율'], 'RSI': ind['RSI']
                    })
                elif signal == "SELL":
                    sell_signals.append({
                        'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'],
                        'volume_krw': ind['거래량_krw_billion'], 'atr_ratio': ind['ATR비율'],
                        'volume_ratio': ind['거래량비율'], 'RSI': ind['RSI']
                    })
            except Exception as e:
                print(f"⚠️ {ticker} 신호 분석 중 오류: {e}")
                continue

        buy_signals = sorted(buy_signals, key=lambda x: x['atr_ratio'])
        sell_signals = sorted(sell_signals, key=lambda x: x['atr_ratio'])

        section = f"<h2>[{name}: 티커 {len(ticker_list)}개, 매수 {len(buy_signals)}개, 매도 {len(sell_signals)}개]</h2>"
        
        buy_html = ""
        for s in buy_signals:
            buy_html += f"""
            <li><b>{s['ticker']}</b>: 매수
                (종가 ${s['close']:.2f} ({format_krw(s['close_krw'])}), 거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x,
                ATR비율 {s['atr_ratio']:.2f}%, RSI {s['RSI']:.2f}, 목표가 ${s['target']:.2f} ({format_krw(s['target_krw'])}), 손절가 ${s['stop']:.2f} ({format_krw(s['stop_krw'])}))
            </li>
            """

        sell_html = ""
        for s in sell_signals:
            sell_html += f"""
            <li><b>{s['ticker']}</b>: 매도
                (종가 ${s['close']:.2f} ({format_krw(s['close_krw'])}), 거래량 {format_krw(s['volume_krw'])}, 거래량비율 {s['volume_ratio']:.1f}x,
                ATR비율 {s['atr_ratio']:.2f}%, RSI {s['RSI']:.2f})
            </li>
            """

        return section + \
                "<h3>🟢 BUY 신호</h3><ul>" + (buy_html if buy_html else "<li>없음</li>") + "</ul>" + \
                "<h3>🔴 SELL 신호</h3><ul>" + (sell_html if sell_html else "<li>없음</li>") + "</ul>"

    report_body += generate_section(sp500_tickers, "S&P500")
    report_body += generate_section(nasdaq100_tickers, "NASDAQ100")

    
    # 백테스팅 결과 추가
    if data:
        backtest_results_html = "<h2>📊 전략 백테스팅 결과 (지난 1년)</h2>"
        tickers_to_backtest = list(data.keys())[:10]  # 상위 10개 종목만 테스트
        for ticker in tickers_to_backtest:
            try:
                result = backtest_strategy(data[ticker])
                if result is not None:
                    backtest_results_html += f"<p><b>{ticker}</b>: {result:.2f}%</p>"
                else:
                    backtest_results_html += f"<p><b>{ticker}</b>: 백테스팅 데이터 부족</p>"
            except Exception as e:
                backtest_results_html += f"<p><b>{ticker}</b>: 백테스팅 오류 - {e}</p>"
        
        report_body += backtest_results_html

    send_email(subject, report_body)
    print("✅ 리포트 생성 및 전송 완료!")
