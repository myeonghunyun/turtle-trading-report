# get_tickers.py
import pandas as pd
import sys
from urllib.request import urlopen, Request

def get_wiki_tickers(url, col_name):
    """Wikipedia에서 티커 목록을 가져옵니다."""
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req) as resp:
            tables = pd.read_html(resp.read())
            
        tickers = []
        for table in tables:
            if col_name in table.columns:
                tickers = table[col_name].dropna().astype(str).tolist()
                tickers = [t.strip() for t in tickers if isinstance(t, str) and 1 <= len(t) <= 10]
                break
        
        if not tickers:
            print(f"❌ '{col_name}' 열을 포함한 테이블을 찾을 수 없습니다. URL: {url}")
            return []
            
        print(f"✅ {len(tickers)}개의 티커를 성공적으로 가져왔습니다.")
        return tickers

    except Exception as e:
        print(f"❌ 티커 가져오기 실패: {e}")
        return []

def main():
    sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    nasdaq100_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'

    sp500_tickers = get_wiki_tickers(sp500_url, 'Symbol')
    nasdaq100_tickers = get_wiki_tickers(nasdaq100_url, 'Ticker')

    all_tickers = sorted(list(set(sp500_tickers + nasdaq100_tickers)))

    if not all_tickers:
        print("❌ 티커 목록이 비어 있습니다. 작업을 중단합니다.")
        sys.exit(1)
        
    # 티커 목록을 tickers.txt 파일로 저장
    with open('tickers.txt', 'w') as f:
        for ticker in all_tickers:
            f.write(ticker + '\n')
            
    print(f"✅ 총 {len(all_tickers)}개의 티커가 tickers.txt에 저장되었습니다.")

if __name__ == '__main__':
    main()
