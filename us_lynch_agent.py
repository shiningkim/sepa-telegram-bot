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
# 3. 메인 실행 루틴
