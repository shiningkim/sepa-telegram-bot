import os
import time
import requests
import pandas as pd
import yfinance as yf
from io import StringIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 0. 텔레그램 다중 방 동시 전송 함수 (쉼표 구분 지원)
# ==========================================
def send_telegram_msg(message: str):
    chat_ids = [cid.strip() for cid in str(CHAT_ID).split(",") if cid.strip()]
    
    for cid in chat_ids:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": cid,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    break
            except Exception as e:
                print(f"[{cid}] 전송 오류 ({attempt}/3): {e}")
                time.sleep(2)

# ==========================================
# 1. 피셔식 톱다운(Top-Down) 매크로 & 섹터 진단
# ==========================================
def analyze_fisher_macro_and_sectors():
    macro_tickers = ["SPY", "IWM", "^VIX", "^TNX", "^IRX"]
    data = yf.download(macro_tickers, period="1y", progress=False)['Close']
    
    spy_curr = data["SPY"].iloc[-1]
    spy_200 = data["SPY"].rolling(200).mean().iloc[-1]
    spy_gap = (spy_curr - spy_200) / spy_200 * 100
    
    vix_curr = data["^VIX"].iloc[-1]
    yield_spread = data["^TNX"].iloc[-1] - data["^IRX"].iloc[-1]
    
    # 스타일 로테이션: 대형주(SPY) vs 소형주(IWM) 3개월(60일) 상대강도
    spy_3m = (data["SPY"].iloc[-1] / data["SPY"].iloc[-60] - 1) * 100
    iwm_3m = (data["IWM"].iloc[-1] / data["IWM"].iloc[-60] - 1) * 100
    style_winner = "대형주 우위 (Large-Cap)" if spy_3m >= iwm_3m else "중소형주 우위 (Small-Cap)"

    # 시장 체제 판별 (피셔식 강세/방어 진단)
    if spy_curr > spy_200 and vix_curr < 22 and yield_spread > -0.5:
        regime = "🟢 공격적 주식 비중 확대 (Wall of Worry 강세장)"
    elif spy_curr < spy_200 or vix_curr >= 28:
        regime = "🔴 방어적 태세 (경기 둔화 경계, 고마진 저PSR 방어주 선별)"
    else:
        regime = "🟡 중립/선별적 접근 (섹터 로테이션 및 밸류에이션 중시)"

    # 미국 11대 섹터 ETF 모멘텀 랭킹 (3개월 수익률 + 200일선 이격도)
    sectors = {
        "XLK": "기술/반도체", "XLF": "금융", "XLV": "헬스케어",
        "XLI": "산업재/방산", "XLE": "에너지", "XLY": "임의소비재",
        "XLP": "필수소비재", "XLU": "유틸리티", "XLB": "소재",
        "XLRE": "부동산", "XLC": "커뮤니케이션"
    }
    sec_df = yf.download(list(sectors.keys()), period="1y", progress=False)['Close']
    sec_ranks = []
    for sym, kname in sectors.items():
        s_curr = sec_df[sym].iloc[-1]
        s_200 = sec_df[sym].rolling(200).mean().iloc[-1]
        ret_3m = (s_curr / sec_df[sym].iloc[-60] - 1) * 100
        if s_curr > s_200:
            sec_ranks.append((sym, kname, round(ret_3m, 1)))
            
    sec_ranks.sort(key=lambda x: x[2], reverse=True)
    top_sectors = sec_ranks[:3]

    return {
        "regime": regime,
        "spy_gap": round(spy_gap, 1),
        "vix": round(vix_curr, 1),
        "spread": round(yield_spread, 2),
        "style": style_winner,
        "top_sectors": top_sectors
    }

# ==========================================
# 2. S&P 500 종목 리스트 확보 (403 차단 우회)
# ==========================================
def get_sp500_tickers():
    # 1순위: 차단이 없는 안정적인 공개 CSV 데이터셋
    csv_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    try:
        df = pd.read_csv(csv_url)
        return [str(t).replace('.', '-').strip() for t in df['Symbol'].tolist()]
    except Exception:
        pass

    # 2순위(백업): User-Agent 헤더를 포함한 위키피디아 파싱
    wiki_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    resp = requests.get(wiki_url, headers=headers, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    return [str(t).replace('.', '-').strip() for t in df['Symbol'].tolist()]

# ==========================================
# 3. 피셔식 정량 펀더멘털 필터 (PSR + 매출총이익률 + 추세)
# ==========================================
def screen_fisher_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if len(hist) < 200:
            return None

        curr_p = hist['Close'].iloc[-1]
        sma200 = hist['Close'].rolling(200).mean().iloc[-1]
        
        # 1) 기술적 최소 안전장치: 하락 추세(200일선 아래) 가치 함정 배제
        if curr_p <= sma200:
            return None

        info = stock.info
        psr = info.get("priceToSalesTrailing12Months")
        gross_margin = info.get("grossMargins")
        rev_growth = info.get("revenueGrowth")
        debt_to_equity = info.get("debtToEquity")
        name = info.get("shortName", ticker)
        sector = info.get("sector", "N/A")

        if psr is None or gross_margin is None or rev_growth is None:
            return None

        # 2) 피셔 핵심 정량 조건
        is_low_psr = (0 < psr <= 3.0)
        is_high_margin = (gross_margin >= 0.35)
        is_growing = (rev_growth >= 0.05)
        is_healthy_debt = (debt_to_equity is None or debt_to_equity <= 150)

        if is_low_psr and is_high_margin and is_growing and is_healthy_debt:
            fisher_score = (gross_margin * 100) / psr
            return {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "price": round(curr_p, 2),
                "psr": round(psr, 2),
                "gm": round(gross_margin * 100, 1),
                "rev_g": round(rev_growth * 100, 1),
                "score": round(fisher_score, 1)
            }
    except Exception:
        return None
    return None

def main():
    print("1. 피셔 매크로 & 섹터 진단 실행 중...")
    macro = analyze_fisher_macro_and_sectors()
    
    print("2. S&P 500 우량 저PSR·고마진 기업 스크리닝 중...")
    tickers = get_sp500_tickers()
    print(f"대상 종목 수: {len(tickers)}개")
    
    passed = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(screen_fisher_stock, t): t for t in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed.append(res)

    passed.sort(key=lambda x: x['score'], reverse=True)

    msg = "🏛️ *[미국장 피셔 인베스트먼트 퀀트 브리핑]*\n"
    msg += "_기준: 톱다운 매크로 체제 + 주도 섹터 + 저PSR(≤3.0) & 고마진(≥35%) 우량주_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "🧭 *1. 톱다운 시장 체제 진단*\n"
    msg += f"• 상태: *{macro['regime']}*\n"
    msg += f"• S&P500 200일선 이격: `{macro['spy_gap']}%` / VIX: `{macro['vix']}`\n"
    msg += f"• 장단기 금리차(10Y-3M): `{macro['spread']}%p`\n"
    msg += f"• 스타일 우위: `{macro['style']}`\n\n"

    msg += "📊 *2. 모멘텀 상위 주도 섹터 (3개월 RS)*\n"
    if macro['top_sectors']:
        for idx, (sym, kname, ret) in enumerate(macro['top_sectors'], 1):
            msg += f"  {idx}위. *{kname}* (`{sym}`): `+{ret}%`\n"
    else:
        msg += "  • 현재 200일선 위에 안착한 강세 섹터가 없습니다 (방어 국면).\n"
    msg += "\n━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += f"💎 *3. 피셔식 저PSR·고마진 우량주 TOP 10 (총 {len(passed)}개 통과)*\n\n"
    if passed:
        for idx, s in enumerate(passed[:10], 1):
            msg += f"{idx}. *{s['name']}* (`{s['ticker']}`): `${s['price']}`\n"
            msg += f"   • 섹터: {s['sector']}\n"
            msg += f"   • PSR: `{s['psr']}배` | 매출총이익률: `{s['gm']}%` | 매출성장: `+{s['rev_g']}%`\n\n"
        msg += "👉 *피셔 전략 가이드*: PSR이 낮고 매출총이익률이 높은 기업 중, 위 2번 주도 섹터에 속한 종목을 중장기 분할 매수합니다."
    else:
        msg += "ℹ️ 현재 200일선 위에서 저PSR·고마진 조건을 모두 만족하는 종목이 없습니다."

    send_telegram_msg(msg)
    print("전송 완료!")

if __name__ == "__main__":
    main()
