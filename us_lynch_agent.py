import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_msg(message: str):
    """텔레그램 메시지 전송 (3회 재시도 + 마크다운 실패 시 텍스트 폴백)"""
    if not BOT_TOKEN or not CHAT_ID:
        print("[Telegram] 토큰 또는 Chat ID가 설정되지 않았습니다.\n" + message)
        return
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                return
            else:
                # 마크다운 특수문자 에러 시 일반 텍스트 재시도
                payload.pop("parse_mode", None)
                resp_fb = requests.post(url, json=payload, timeout=25)
                if resp_fb.status_code == 200:
                    return
        except Exception as e:
            print(f"[{attempt}/3] 텔레그램 전송 실패: {e}")
        time.sleep(2)

# ==========================================
# 1. 미국 상장 유니버스 수집 (기존 프로그램과 100% 동일)
# ==========================================
def get_us_tickers() -> list:
    url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
    try:
        resp = requests.get(url, timeout=15)
        raw_tickers = resp.text.strip().split("\n")
        cleaned = [
            t.strip().replace(".", "-") for t in raw_tickers 
            if t.strip() and not any(c in t for c in ["^", "/", "~", "$", "+"])
        ]
        return cleaned[:2500]
    except Exception:
        # 비상용 기본 티커 목록
        return ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "CROX", "ELF", "DECK", "MEDP", "LULU", "FSLR"]

# ==========================================
# 2. 피터 린치 펀더멘털 정밀 검증
# ==========================================
def check_peter_lynch_fundamentals(ticker: str) -> dict:
    """
    피터 린치 핵심 기준:
    1. PEG < 1.0 (0.5 이하는 초우수)
    2. 건전한 성장률: EPS 성장률 15% ~ 45% (과열 잡주 배제)
    3. 부채비율(D/E): 80% 이하 (안전한 재무구조)
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info

        # PER (Trailing 우선, 없으면 Forward)
        pe = info.get("trailingPE") or info.get("forwardPE")
        
        # 성장률 (이익 성장률 우선, 없으면 매출 성장률)
        growth = info.get("earningsGrowth") or info.get("revenueGrowth")
        
        # 부채비율
        de = info.get("debtToEquity", 50.0)

        if not pe or not growth or pe <= 0 or growth <= 0:
            return None

        growth_pct = growth * 100
        peg = pe / growth_pct

        # 린치 기준 필터: PEG 1.0 미만, 성장률 15~45%, 부채비율 80% 이하
        is_lynch_pass = (peg < 1.0) and (15.0 <= growth_pct <= 45.0) and (de <= 80.0)

        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)

        return {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "price": round(price, 2),
            "pe": round(pe, 2),
            "growth": round(growth_pct, 2),
            "peg": round(peg, 2),
            "de": round(de, 2),
            "is_pass": is_lynch_pass
        }
    except Exception:
        return None

# ==========================================
# 3. 메인 실행 루틴 (1차 가격/거래대금 압축 -> 2차 린치 지표 검증)
# ==========================================
def main():
    tickers = get_us_tickers()
    print(f"미국 피터 린치 스크리너 시작 (총 유니버스: {len(tickers)}개)...")

    # 1단계: yf.download를 통한 기본 유동성 1차 필터링 ($10 이상, 50일 평균 거래대금 300만 달러 이상)
    liquid_candidates = []
    batch_size = 100

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            data = yf.download(batch, period="3mo", group_by='ticker', threads=True, progress=False)
            for ticker in batch:
                try:
                    df = data[ticker] if len(batch) > 1 else data
                    df = df.dropna(subset=['Close'])
                    if len(df) < 40:
                        continue
                    
                    close = df['Close']
                    volume = df['Volume']
                    current_price = close.iloc[-1]
                    vol_avg50 = volume.mean()
                    dollar_vol = current_price * vol_avg50

                    # 피터 린치는 가격 차트 정배열은 보지 않으나, 상장폐지급/거래불가 잡주는 배제
                    if current_price >= 10.0 and dollar_vol >= 3000000:
                        liquid_candidates.append(ticker)
                except Exception:
                    continue
        except Exception:
            continue

    print(f"1차 유동성 필터 통과: {len(liquid_candidates)}개 종목. 2차 린치 지표 검증 시작...")

    # 2단계: 린치 정량 밸류에이션(PEG, D/E) 검증 (실행 시간 고려 상위 200개 우선 정밀 분석)
    lynch_hits = []
    scanned_count = 0

    for ticker in liquid_candidates[:200]:
        res = check_peter_lynch_fundamentals(ticker)
        if res:
            scanned_count += 1
            if res["is_pass"]:
                lynch_hits.append(res)
        time.sleep(0.1)  # Yahoo API 호출 딜레이

    # PEG가 낮은 순(성장 대비 가장 저평가된 순) 정렬
    lynch_hits = sorted(lynch_hits, key=lambda x: x["peg"])

    # ==========================================
    # 텔레그램 발송
    # ==========================================
    total_found = len(lynch_hits)
    msg = "📖 *[피터 린치 Agent - 미국 저평가 고성장주]*\n"
    msg += f"• **검사 대상**: {scanned_count}개 종목 (1차 유동성 통과군 기준)\n"
    msg += f"• **통과 종목**: 총 {total_found}개 포착\n"
    msg += "• **기준**: `PEG < 1.0` + `이익성장 15~45%` + `부채비율 ≤ 80%`\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if lynch_hits:
        for idx, item in enumerate(lynch_hits[:15], 1):
            peg_badge = "🔥 초우수" if item['peg'] <= 0.5 else "✨ 우수"
            msg += f"*{idx}위. {item['ticker']}* ({item['name']}): `${item['price']}`\n"
            msg += f"   • **PEG**: `{item['peg']}` ({peg_badge})\n"
            msg += f"   • 실적: PER `{item['pe']}배` / 성장률 `{item['growth']}%`\n"
            msg += f"   • 부채비율: `{item['de']}%`\n\n"
        
        msg += "👉 *실전 전략*: 미네르비니 기준에서 아직 정배열이 아니더라도, 실적 성장 대비 주가가 눌려 있는 턴어라운드/선취매 슬롯으로 분할 진입을 고려하십시오."
    else:
        msg += "ℹ️ 현재 유니버스에서 린치의 엄격한 저평가 고성장 기준을 통과한 종목이 없습니다."

    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
