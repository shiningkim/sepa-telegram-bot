import os
import time
import requests
import pandas as pd
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram 미설정 - 콘솔 출력]\n" + text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        print(f"텔레그램 전송 에러: {resp.status_code} - {resp.text}")

def get_sp500_tickers(limit=150):
    """위키피디아에서 S&P 500 티커 리스트 자동 수집"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        tables = pd.read_html(requests.get(url, headers=headers).text)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return tickers[:limit] if limit else tickers
    except Exception as e:
        print(f"S&P 500 리스트 수집 실패: {e}")
        # 폴백용 기본 준대형/중형 유망주 리스트
        return [
            "CROX", "ELF", "DECK", "MEDP", "LULU", "ON", "FSLR", "ANET", 
            "FTNT", "URI", "PWR", "FIX", "VRT", "SMCI", "PHM", "LEN"
        ]

def screen_us_stock(ticker: str):
    try:
        t = yf.Ticker(ticker)
        # fast_info 및 info 혼용 접근
        info = t.info

        pe = info.get("trailingPE") or info.get("forwardPE")
        growth = info.get("earningsGrowth") or info.get("revenueGrowth")
        de = info.get("debtToEquity", 50.0)

        if not pe or not growth or pe <= 0 or growth <= 0:
            return None

        growth_pct = growth * 100
        peg = pe / growth_pct

        # 린치 기준: PEG < 1.0, 지속 가능한 성장률(15~45%), 부채비율 80% 이하
        is_hit = (peg < 1.0) and (15.0 <= growth_pct <= 45.0) and (de <= 80.0)

        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)

        return {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "price": price,
            "pe": round(pe, 2),
            "growth": round(growth_pct, 2),
            "peg": round(peg, 2),
            "de": round(de, 2),
            "is_hit": is_hit
        }
    except Exception:
        return None

def main():
    print("S&P 500 유니버스 수집 중...")
    # Actions 실행 시간 고려: S&P 500 중 상위 120개 검사 (전체 검사를 원하면 limit=None)
    universe = get_sp500_tickers(limit=120)
    
    hits = []
    scanned_count = 0

    for ticker in universe:
        res = screen_us_stock(ticker)
        if res:
            scanned_count += 1
            if res["is_hit"]:
                hits.append(res)
        # yfinance Rate Limit 방지용 딜레이
        time.sleep(0.15)

    if hits:
        # PEG 낮은 순(저평가 우수 순) 상위 10개 정렬
        hits = sorted(hits, key=lambda x: x["peg"])[:10]

        msg = f"🇺🇸 *[피터 린치 Agent - 미국 저평가 고성장주]*\n"
        msg += f"• 검사: {scanned_count}개 / 통과: {len(hits)}개\n\n"
        for item in hits:
            msg += f"• *{item['name']} ({item['ticker']})*\n"
            msg += f"  - 주가: ${item['price']}\n"
            msg += f"  - PEG: `{item['peg']}` (PER {item['pe']} / 성장률 {item['growth']}%)\n"
            msg += f"  - 부채비율: `{item['de']}%`\n\n"
    else:
        msg = f"🇺🇸 *[피터 린치 Agent - 미국 스크리닝 완료]*\n"
        msg += f"• 총 {scanned_count}개 종목 검사 완료\n"
        msg += f"• 현재 조건(`PEG < 1.0`, `성장률 15~45%`, `부채비율 ≤ 80%`)을 통과한 종목이 없습니다."

    send_telegram(msg)

if __name__ == "__main__":
    main()
