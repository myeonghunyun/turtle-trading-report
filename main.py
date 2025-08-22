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
import numpy as np

# ----------------- 설정값을 외부 파일에서 불러오기 -----------------
def read_settings(file_path='settings.txt'):
    settings = {}
    if not os.path.exists(file_path):
        print(f"❌ 설정 파일 '{file_path}'이 없습니다. 프로그램을 종료합니다.")
        sys.exit(1)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, value = line.split('=')
            settings[key.strip()] = value.strip()
            
    try:
        return {
            'TOTAL_SEED_KRW': int(settings['TOTAL_SEED_KRW']),
            'MAX_LOSS_RATE': float(settings['MAX_LOSS_RATE']),
            'VOLUME_THRESHOLD': float(settings['VOLUME_THRESHOLD']),
            'ADX_THRESHOLD': int(settings['ADX_THRESHOLD']),
            'ATR_UPPER_LIMIT': float(settings['ATR_UPPER_LIMIT']),
            'SECTOR_LIMIT': int(settings['SECTOR_LIMIT']),
            'FORWARD_PER': float(settings['FORWARD_PER'])
        }
    except KeyError as e:
        print(f"❌ 설정 파일에 필수 항목 '{e}'이(가) 누락되었습니다.")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ 설정 파일의 값 형식이 올바르지 않습니다: {e}")
        sys.exit(1)

# ----------------- 설정값을 전역 변수로 설정 -----------------
SETTINGS = read_settings()
TOTAL_SEED_KRW = SETTINGS['TOTAL_SEED_KRW']
MAX_LOSS_RATE = SETTINGS['MAX_LOSS_RATE']
VOLUME_THRESHOLD = SETTINGS['VOLUME_THRESHOLD']
ADX_THRESHOLD = SETTINGS['ADX_THRESHOLD']
ATR_UPPER_LIMIT = SETTINGS['ATR_UPPER_LIMIT']
SECTOR_LIMIT = SETTINGS['SECTOR_LIMIT']
FORWARD_PER = SETTINGS['FORWARD_PER']
MAX_UNITS = 4

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

def get_turtle_signal(ticker_data, vix_value, exchange_rate, dynamic_adx_threshold, dynamic_atr_upper_limit, last_buy_price=None, units=0):
    """단일 종목에 대한 터틀 트레이딩 신호를 계산합니다."""
    try:
        if not isinstance(ticker_data, pd.DataFrame) or ticker_data.empty:
            return "데이터 없음", {}

        ticker_data = ticker_data.ffill().dropna()
        if ticker_data.empty or len(ticker_data) < 200:
            return "데이터 부족", {}

        ticker_data['ATR'] = ta.atr(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=20)
        adx_series = ta.adx(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=14)
        if adx_series is not None and not adx_series.empty:
            ticker_data['ADX'] = adx_series['ADX_14']
            ticker_data['+DI'] = adx_series['DMP_14']
            ticker_data['DMN_14'] = adx_series['DMN_14']
        ticker_data['MA200'] = ta.sma(ticker_data['Close'], length=200)
        ticker_data['RSI'] = ta.rsi(ticker_data['Close'], length=14)
        ticker_data['VMA20'] = ta.sma(ticker_data['Volume'], length=20)

        if ticker_data.iloc[-1].isnull().any():
            return "분석 오류", {}

        last_row = ticker_data.iloc[-1]
        last_close = last_row['Close']
        last_volume = last_row['Volume']
        last_atr = last_row['ATR']
        last_adx = last_row['ADX'] if pd.notna(last_row['ADX']) else 0
        last_plus_di = last_row['+DI'] if pd.notna(last_row['+DI']) else 0
        last_minus_di = last_row['DMN_14'] if pd.notna(last_row['DMN_14']) else 0
        last_ma200 = last_row['MA200'] if pd.notna(last_row['MA200']) else 0
        last_rsi = last_row['RSI'] if pd.notna(last_row['RSI']) else 0

        last_20_high_prev = ticker_data['High'].iloc[:-1].rolling(20).max().iloc[-1] if len(ticker_data) >= 21 else last_close
        last_10_low = ticker_data['Low'].rolling(10).min().iloc[-1] if len(ticker_data) >= 10 else last_close

        avg_volume_20d = ticker_data['Volume'].rolling(window=20).mean().iloc[-1]
        volume_ratio = last_volume / avg_volume_2d if avg_volume_2d > 0 else 0
        
        last_vma20 = last_row['VMA20']
        volume_above_vma = last_volume > last_vma20 if last_vma20 > 0 else False

        avg_atr_20d = ticker_data['ATR'].rolling(window=20).mean().iloc[-1]
        atr_above_avg = last_atr > avg_atr_20d

        disparity_rate = (last_close - last_ma200) / last_ma200 * 100 if last_ma200 > 0 else 0
        atr_ratio = (last_atr / last_close) * 100 if last_close > 0 else 0

        max_loss_usd = (TOTAL_SEED_KRW * MAX_LOSS_RATE) / exchange_rate
        loss_per_share = last_atr * 2
        buy_quantity = int(max_loss_usd / loss_per_share) if loss_per_share > 0 else 0
        
        stop_price = last_close - (2 * last_atr)
        target_price = last_close + (2 * last_atr)

        if units > 0 and last_buy_price is not None:
            stop_price_portfolio = last_buy_price - (2 * last_atr)
            pyramid_price = last_buy_price + (0.5 * last_atr)
            
            if last_close < stop_price_portfolio or last_close < last_10_low:
                return "SELL", {
                    "종가": last_close, "종가_krw": round(last_close * exchange_rate, 0), "ATR": last_atr,
                    "손절가": round(stop_price_portfolio * exchange_rate, 0), "손절가_usd": stop_price_portfolio,
                    "매수포함": True, "ADX": last_adx, "+DI": last_plus_di, "-DI": last_minus_di,
                    "MA200": last_ma200, "괴리율": disparity_rate, "RSI": last_rsi, "atr_ratio": atr_ratio,
                    "volume_krw_billion": (last_volume * last_close * exchange_rate) / 1e8, "volume_ratio": volume_ratio
                }
            elif last_close > pyramid_price and units < MAX_UNITS:
                return "PYRAMID_BUY", {
                    "종가": last_close, "종가_krw": round(last_close * exchange_rate, 0), "ATR": last_atr,
                    "추가매수가": round(pyramid_price * exchange_rate, 0), "추가매수가_usd": pyramid_price,
                    "매수포함": True, "ADX": last_adx, "+DI": last_plus_di, "-DI": last_minus_di,
                    "MA200": last_ma200, "괴리율": disparity_rate, "RSI": last_rsi, "atr_ratio": atr_ratio,
                    "volume_krw_billion": (last_volume * last_close * exchange_rate) / 1e8, "volume_ratio": volume_ratio
                }
            else:
                return "보유", {
                    "종가": last_close, "종가_krw": round(last_close * exchange_rate, 0), "ATR": last_atr,
                    "손절가": round(stop_price_portfolio * exchange_rate, 0), "손절가_usd": stop_price_portfolio,
                    "매수포함": True, "ADX": last_adx, "+DI": last_plus_di, "-DI": last_minus_di,
                    "MA200": last_ma200, "괴리율": disparity_rate, "RSI": last_rsi, "atr_ratio": atr_ratio,
                    "volume_krw_billion": (last_volume * last_close * exchange_rate) / 1e8, "volume_ratio": volume_ratio
                }

        is_above_ma200 = last_close > last_ma200
        initial_buy_condition = (
            last_close > last_20_high_prev and
            is_above_ma200 and
            vix_value < 30 and
            last_adx > dynamic_adx_threshold and
            volume_ratio > VOLUME_THRESHOLD and
            volume_above_vma and
            atr_above_avg and
            last_rsi < 70 and
            atr_ratio <= dynamic_atr_upper_limit
        )

        if initial_buy_condition and units == 0:
            signal = "BUY"
        elif not is_above_ma200 or last_adx < dynamic_adx_threshold or last_close < last_10_low:
            signal = "SELL"
        else:
            signal = "보유"

        indicators = {
            "종가": last_close, "종가_krw": round(last_close * exchange_rate, 0), "거래량_krw_billion": (last_volume * last_close * exchange_rate) / 1e8,
            "ATR": last_atr, "ATR비율": atr_ratio, "MA200": last_ma200, "괴리율": disparity_rate,
            "ADX": last_adx, "+DI": last_plus_di, "-DI": last_minus_di, "거래량비율": volume_ratio,
            "손절가": round(stop_price * exchange_rate, 0), "목표가": round(target_price * exchange_rate, 0), "매수가능수량": buy_quantity, "RSI": last_rsi,
            "손절가_usd": stop_price, "목표가_usd": target_price, "매수포함": False
        }

        return signal, indicators

    except Exception as e:
        print(f"❌ 분석 중 오류: {e}")
        return "오류", {}

def send_email(subject, body):
    """리포트를 이메일로 전송합니다."""
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    
    receiver_emails_str = os.getenv("RECEIVER_EMAIL")
    if not receiver_emails_str:
        print("❌ 이메일 설정이 누락되었습니다. Secrets를 확인하세요.")
        return
        
    receiver_emails = [email.strip() for email in receiver_emails_str.split(',')]

    if not all([sender_email, sender_password]):
        print("❌ 이메일 설정이 누락되었습니다. Secrets를 확인하세요.")
        return

    body_clean = body.replace('\xa0', ' ').replace('\u00A0', ' ')
    msg = MIMEText(body_clean, 'html', _charset='utf-8')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_emails_str

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_emails, msg.as_string())
        print("✅ 이메일이 성공적으로 전송되었습니다.")
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {e}")

def get_ticker_sector_industry(ticker):
    """yfinance를 통해 티커의 섹터와 산업 정보를 가져옵니다."""
    try:
        info = yf.Ticker(ticker).info
        return info.get('sector', 'Unknown'), info.get('industry', 'Unknown')
    except:
        return 'Unknown', 'Unknown'

def read_positions_file(file_path='positions.csv'):
    """포지션 파일을 읽어와서 DataFrame으로 반환합니다."""
    if not os.path.exists(file_path):
        print(f"⚠️ {file_path} 파일이 없습니다. 빈 포지션으로 시작합니다.")
        return pd.DataFrame(columns=['ticker', 'buy_date', 'buy_price', 'units'])
    try:
        return pd.read_csv(file_path)
    except Exception as e:
        print(f"❌ {file_path} 파일 로드 중 오류 발생: {e}")
        return pd.DataFrame(columns=['ticker', 'buy_date', 'buy_price', 'units'])

def backtest_strategy(ticker_data, dynamic_adx_threshold):
    """단순 백테스팅을 통해 전략의 수익률과 최대 낙폭(MDD)을 계산합니다."""
    if ticker_data.empty or len(ticker_data) < 250:
        return None, None

    signals = pd.DataFrame(index=ticker_data.index)
    signals['Close'] = ticker_data['Close']
    signals['Position'] = 0
    signals['Strategy'] = 1.0

    signals['MA200'] = ta.sma(signals['Close'], length=200)
    signals['RSI'] = ta.rsi(signals['Close'], length=14)
    adx_series = ta.adx(ticker_data['High'], ticker_data['Low'], ticker_data['Close'], length=14)
    if adx_series is not None and not adx_series.empty:
        signals['ADX'] = adx_series['ADX_14']
    signals['20D_High'] = ticker_data['High'].rolling(20).max()
    signals['10D_Low'] = ticker_data['Low'].rolling(10).min()

    for i in range(200, len(signals)):
        prev_close = signals.loc[signals.index[i-1], 'Close']
        current_close = signals.loc[signals.index[i], 'Close']
        
        buy_condition = (
            current_close > signals.loc[signals.index[i-1], '20D_High'] and
            current_close > signals.loc[signals.index[i], 'MA200'] and
            signals.loc[signals.index[i], 'ADX'] > dynamic_adx_threshold and
            signals.loc[signals.index[i], 'RSI'] < 70
        )
        sell_condition = (
            current_close < signals.loc[signals.index[i], 'MA200'] or
            signals.loc[signals.index[i], 'ADX'] < dynamic_adx_threshold or
            current_close < signals.loc[signals.index[i], '10D_Low']
        )

        if buy_condition and signals.loc[signals.index[i-1], 'Position'] == 0:
            signals.loc[signals.index[i], 'Position'] = 1
        elif sell_condition and signals.loc[signals.index[i-1], 'Position'] == 1:
            signals.loc[signals.index[i], 'Position'] = 0
        else:
            signals.loc[signals.index[i], 'Position'] = signals.loc[signals.index[i-1], 'Position']

        if signals.loc[signals.index[i-1], 'Position'] == 1:
            return_rate = (current_close / prev_close) - 1
            signals.loc[signals.index[i], 'Strategy'] = signals.loc[signals.index[i-1], 'Strategy'] * (1 + return_rate)
        else:
            signals.loc[signals.index[i], 'Strategy'] = signals.loc[signals.index[i-1], 'Strategy']

    if not signals['Strategy'].empty:
        total_return = (signals['Strategy'].iloc[-1] - 1) * 100
        
        cumulative_returns = signals['Strategy']
        peak = cumulative_returns.expanding(min_periods=1).max()
        drawdown = (cumulative_returns - peak) / peak
        max_drawdown = drawdown.min() * 100 if not drawdown.empty else 0
        return total_return, max_drawdown
    return None, None

def generate_detailed_stock_report_html(s, action):
    """
    주식 매매 리포트의 HTML 항목을 생성하는 함수
    """
    target_stop_html = ""
    if action == 'BUY':
        target_stop_html = f"→ <b>매수 가능 수량</b>: {s['quantity']:,}주<br>→ 목표가: ${s['target']:.2f}, 손절가: ${s['stop']:.2f}"
    elif action == 'PYRAMID_BUY':
        target_stop_html = f"→ <b>추가 매수 가격</b>: ${s['pyramid_price_usd']:.2f} (현재 {s['units']} 유닛 보유)<br>→ 손절가: ${s['stop']:.2f}"
    elif action == 'SELL':
        target_stop_html = f"→ <b>현재 보유 수량</b>: {s['units']}주<br>→ 매도 가격: ${s['close']:.2f}, 손절가: ${s['stop']:.2f}"
    elif action == '보유':
        target_stop_html = f"→ <b>현재 보유 수량</b>: {s['units']}주 (추세 유지 중)<br>→ 손절가: ${s['stop']:.2f}"

    report_html = f"""
    <li>
        <b>{s['ticker']}</b> ({s['sector']}) : {action}
        <br>
        (종가 ${s['close']:.2f}, ATR: ${s['atr']:.2f}, ATR비율: {s['atr_ratio']:.2f}%, MA200: ${s['ma200']:.2f}, 괴리율: {s['괴리율']:.2f}%, ADX: {s['adx']:.2f}, +DI: {s['+di']:.2f}, -DI: {s['-di']:.2f})
        <br>
        {target_stop_html}
    </li>
    """
    return report_html

# ================ 메인 실행 ==================
if __name__ == '__main__':
    print("🚀 터틀 트레이딩 리포트 시작...")
    REPORT_TYPE = os.getenv("REPORT_TYPE", "morning_plan")
    
    session = curl_requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    EXCHANGE_RATE_KRW_USD = 1394.00
    try:
        forex_data = yf.download("KRW=X", period="1d", auto_adjust=True, session=session, progress=False)
        if forex_data is not None and not forex_data.empty:
            EXCHANGE_RATE_KRW_USD = float(forex_data['Close'].iloc[0])
        else:
            print("⚠️ 환율 데이터가 비어 있습니다. 기본값 사용")
    except Exception as e:
        print(f"⚠️ 환율 가져오기 실패: {e}, 기본값 사용")
    print(f"💱 실시간 환율: 1 USD = {EXCHANGE_RATE_KRW_USD:,.2f} KRW")

    vix_value = 15.09
    try:
        vix_data = yf.download('^VIX', period="5d", auto_adjust=True, session=session, progress=False)
        if vix_data is not None and not vix_data.empty and not vix_data['Close'].dropna().empty:
            vix_value = float(vix_data['Close'].dropna().iloc[0])
        else:
            print("⚠️ VIX 데이터가 비어 있습니다. 기본값 사용")
    except Exception as e:
        print(f"⚠️ VIX 가져오기 실패: {e}, 기본값 사용")
    print(f"📈 VIX 값: {vix_value:.2f}")

    dynamic_adx_threshold = ADX_THRESHOLD
    dynamic_atr_upper_limit = ATR_UPPER_LIMIT
    if vix_value < 20:
        dynamic_adx_threshold = 19
    elif vix_value >= 30:
        dynamic_atr_upper_limit = 4.0

    forward_pe = FORWARD_PER
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

    positions_df = read_positions_file()
    positions_dict = {row['ticker']: row for _, row in positions_df.iterrows()}
    
    data = {}
    failed_tickers = []
    print(f"📊 총 {len(all_tickers)}개 종목 데이터 다운로드 중...")
    
    all_target_tickers = list(set(all_tickers + list(positions_dict.keys())))

    for i, ticker in enumerate(all_target_tickers):
        print(f"({i+1}/{len(all_target_tickers)}) 다운로드 중: {ticker}")
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
    pyramid_signals = []
    sell_signals = []
    sector_counts = {}
    
    def is_a_plus_plus(ind, price_data, sector_name):
        last_atr = price_data['ATR'].iloc[-1]
        avg_atr_20d = price_data['ATR'].rolling(window=20).mean().iloc[-1] if len(price_data) >= 20 else last_atr
        
        if sector_counts.get(sector_name, 0) >= SECTOR_LIMIT:
            return False
            
        return (
            ind['ADX'] > dynamic_adx_threshold and
            ind['+DI'] > ind['-DI'] and
            ind['종가'] > ind['MA200'] and
            1.5 <= ind['ATR비율'] <= dynamic_atr_upper_limit and
            ind['거래량비율'] > VOLUME_THRESHOLD and
            ind['매수가능수량'] > 0 and
            ind['RSI'] < 70 and
            ind['거래량비율'] > 1 and
            ind['거래량'] > price_data['VMA20'].iloc[-1] and
            last_atr > avg_atr_20d
        )
    
    for ticker, price_data in data.items():
        try:
            price_data.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            sector, industry = get_ticker_sector_industry(ticker)
            
            is_holding = ticker in positions_dict
            last_buy_price = positions_dict[ticker]['buy_price'] if is_holding else None
            units = positions_dict[ticker]['units'] if is_holding else 0

            signal, ind = get_turtle_signal(price_data, vix_value, EXCHANGE_RATE_KRW_USD, dynamic_adx_threshold, dynamic_atr_upper_limit, last_buy_price=last_buy_price, units=units)

            if is_holding:
                if signal == "PYRAMID_BUY":
                    pyramid_signals.append({
                        'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'], 'pyramid_price_krw': ind['추가매수가'],
                        'units': units, 'sector': sector, 'atr': ind['ATR'], 'atr_ratio': ind['ATR비율'],
                        'ma200': ind['MA200'], '괴리율': ind['괴리율'], 'adx': ind['ADX'], '+di': ind['+DI'], '-di': ind['DMN_14']
                    })
                elif signal == "SELL":
                    sell_signals.append({
                        'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'], 'stop_price_krw': ind['손절가'],
                        'units': units, 'sector': sector, 'atr': ind['ATR'], 'atr_ratio': ind['ATR비율'],
                        'ma200': ind['MA200'], '괴리율': ind['괴리율'], 'adx': ind['ADX'], '+di': ind['+DI'], '-di': ind['DMN_14']
                    })
            
            if signal == "BUY" and is_a_plus_plus(ind, price_data, sector) and not is_holding:
                a_plus_plus_list.append({
                    'ticker': ticker, 'close': ind['종가'], 'close_krw': ind['종가_krw'],
                    'volume_krw': ind['거래량_krw_billion'], 'atr_ratio': ind['ATR비율'],
                    'target': ind['목표가_usd'], 'stop': ind['손절가_usd'],
                    'target_krw': ind['목표가'], 'stop_krw': ind['손절가'],
                    'quantity': ind['매수가능수량'], 'volume_ratio': ind['거래량비율'], 'RSI': ind['RSI'],
                    'sector': sector, 'industry': industry,
                    'atr': ind['ATR'], 'ma200': ind['MA200'], '괴리율': ind['괴리율'], 'adx': ind['ADX'], '+di': ind['+DI'], '-di': ind['DMN_14']
                })
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
        except Exception as e:
            print(f"⚠️ 분석 중 오류: {e}")
            continue

    a_plus_plus_list = sorted(a_plus_plus_list, key=lambda x: x['atr_ratio'])
    
    backtest_results = {}
    for ticker_data in a_plus_plus_list:
        ticker = ticker_data['ticker']
        result, mdd = backtest_strategy(data[ticker], ADX_THRESHOLD)
        if result is not None:
            backtest_results[ticker] = {'return': result, 'mdd': mdd}

    if REPORT_TYPE == "morning_plan":
        title = "🌅 [계획용] 오전 7시 터틀 트레이딩 리포트"
        subtitle = "장 마감 후, 어제 데이터 기반으로 작성된 <b>계획 수립용 리포트</b>입니다."
        timing_note = "📌 이 리포트는 어제 종가 기준입니다. 장 시작 전에 반드시 실시간 재검토하세요."
    else:
        title = "🌃 [실시간] 오후 10시 터틀 트레이딩 리포트"
        subtitle = "장 시작 직전, <b>프리마켓 실시간 데이터</b>를 반영한 <b>최종 결정용 리포트</b>입니다."
        timing_note = "📌 이 리포트는 프리마켓 가격을 반영했습니다. 매수 주문을 위한 최종 확인이 필요합니다."
    
    subject = f"{title.split('[')[0].strip()} (VIX: {vix_value:.1f}, PER: {forward_pe:.1f})"

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

    atr_ratios = [s['atr_ratio'] for s in a_plus_plus_list if 'atr_ratio' in s]
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
            <td>{FORWARD_PER:.1f}배</td>
            <td>15~16: 평균<br>> 20: 고평가</td>
            <td>{'🔴 고평가' if FORWARD_PER > 20 else '🟠 다소 높음' if FORWARD_PER > 18 else '🟢 정상'}</td>
        </tr>
    </table>

    <h3>💡 시장 상황 종합 판단 및 행동 요령</h3>
    <ul>
    """

    if vix_value < 20 and disparity_sp500 > 10 and FORWARD_PER > 20:
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

    if pyramid_signals or sell_signals:
        report_body += "<h2>🚀 현재 포트폴리오 신호</h2>"
        if pyramid_signals:
            report_body += "<h3>🟢 Pyramiding (추가 매수) 신호</h3><ul>"
            for s in pyramid_signals:
                report_body += f"""
                <li><b>{s['ticker']}</b> ({s['sector']}): 현재 보유 수량 {s['units']}주. 추가 매수 조건 충족
                (현재가 ${s['close']:.2f}, ATR: ${s['atr']:.2f}, ATR비율: {s['atr_ratio']:.2f}%, MA200: ${s['ma200']:.2f}, 괴리율: {s['괴리율']:.2f}%, ADX: {s['adx']:.2f}, +DI: {s['+di']:.2f}, -DI: {s['-di']:.2f})
                <br>
                → 추가 매수 가격: ${s['pyramid_price_usd']:.2f}, 손절가: ${s['stop']:.2f}
                </li>
                """
            report_body += "</ul>"
        if sell_signals:
            report_body += "<h3>🔴 SELL (청산) 신호</h3><ul>"
            for s in sell_signals:
                report_body += f"""
                <li><b>{s['ticker']}</b> ({s['sector']}) : 현재 보유 수량 {s['units']}주. 손절/익절 조건 충족
                (현재가 ${s['close']:.2f}, ATR: ${s['atr']:.2f}, ATR비율: {s['atr_ratio']:.2f}%, MA200: ${s['ma200']:.2f}, 괴리율: {s['괴리율']:.2f}%, ADX: {s['adx']:.2f}, +DI: {s['+di']:.2f}, -DI: {s['-di']:.2f})
                <br>
                → 매도 가격: ${s['close']:.2f}, 손절가: ${s['stop']:.2f}
                </li>
                """
            report_body += "</ul>"
        report_body += "<hr><br/>"
        
    if a_plus_plus_list:
        report_body += "<h2>🌟 나만의 A++ 추천 종목 (고성과 + 안정성)</h2><ul>"
        for s in a_plus_plus_list:
            report_body += f"""
            <li><b>{s['ticker']}</b> ({s['sector']}): A++ 종목 (종가 ${s['close']:.2f},
            ATR: ${s['atr']:.2f}, ATR비율: {s['atr_ratio']:.2f}%, MA200: ${s['ma200']:.2f}, 괴리율: {s['괴리율']:.2f}%, ADX: {s['adx']:.2f}, +DI: {s['+di']:.2f}, -DI: {s['-di']:.2f})
            <br>
            → <b>매수 가능 수량: {s['quantity']:,}주</b>
            <br>
            → 목표가: ${s['target']:.2f}, 손절가: ${s['stop']:.2f}
            </li>
            """
        report_body += "</ul><hr><br/>"
    else:
        report_body += "<h2>🌟 나만의 A++ 추천 종목</h2><p>현재 기준에 맞는 A++ 종목이 없습니다.</p><hr><br/>"
        
    backtest_results = {}
    for ticker_data in a_plus_plus_list:
        ticker = ticker_data['ticker']
        result, mdd = backtest_strategy(data[ticker], ADX_THRESHOLD)
        if result is not None:
            backtest_results[ticker] = {'return': result, 'mdd': mdd}

    if backtest_results:
        report_body += "<h2>📊 전략 백테스팅 결과 (지난 1년)</h2>"
        report_body += """<p>※ 백테스팅 결과는 과거 성과이며, 미래 수익률을 보장하지 않습니다.<br>
            <b>최대 낙폭(MDD)</b>: 전략이 실행된 기간 동안 고점에서 저점까지의 최대 손실률입니다. 전략의 리스크를 파악하는 중요한 지표입니다.</p>"""
        report_body += "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse; font-size: 14px;'>"
        report_body += "<tr><th>종목</th><th>수익률</th><th>최대 낙폭(MDD)</th></tr>"
        
        for ticker, result in backtest_results.items():
            report_body += f"<tr><td><b>{ticker}</b></td><td>{result['return']:.2f}%</td><td>{result['mdd']:.2f}%</td></tr>"
        
        report_body += "</table>"
    else:
        report_body += "<h2>📊 전략 백테스팅 결과 (지난 1년)</h2><p>A++ 종목이 없어 백테스팅을 실행할 수 없습니다.</p>"
    
    send_email(subject, report_body)
    print("✅ 리포트 생성 및 전송 완료!")
