import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_msg(message: str):
    """텔레그램 메시지 전송 (최대 3회 재시도 및 마크다운 에러 시 텍스트 폴백)"""
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
                # 마크다운 특수문자 파싱 에러 방지용 일반 텍스트 재전송
                payload.pop("parse_mode", None)
                resp_fallback = requests.post(url, json=payload, timeout=25)
                if resp_fallback.status_code == 200:
                    return
        except Exception as e:
            print(f"[{attempt}/3] 텔레그램 전송 오류: {e}")
            time.sleep(2)

# ==========================================
# 1. 국내 상장 종목 유니버스 (코스피 200 + 코스닥 300)
# ==========================================
def get_target_tickers():
    """스팩, 우선주, 관리종목을 배제한 시총 상위 500개 종목 수집"""
    df_krx = fdr.StockListing('KRX')
    df_clean = df_krx[~df_krx['Name'].str.contains('스팩|우$|우B$|1호|2호|3호|4호|5호', regex=True, na=False)]
    
    kospi = df_clean[df_clean['Market'] == 'KOSPI'].sort_values(by='Marcap', ascending=False).head(200)
    kosdaq = df_clean[df_clean['Market'] == 'KOSDAQ'].sort_values(by='Marcap', ascending=False).head(300)
    
    targets = []
    for _, row in kospi.iterrows():
        targets.append((row['Code'], row['Name'], '코스피'))
    for _, row in kosdaq.iterrows():
        targets.append((row['Code'], row['Name'], '코스닥'))
    return targets

# ==========================================
# 2. 피터 린치 펀더멘털 정밀 검증 (네이버 모바일 JSON API)
# ==========================================
def check_peter_lynch_kr(ticker, name, market_type):
    """
    피터 린치 핵심 기준:
    1. PEG < 1.0 (PER / 영업이익 성장률)
    2. 최근 연간 영업이익 성장률 >= 15%
    3. 부채비율 <= 100%
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }
    
    basic_url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
    finance_url = f"https://m.stock.naver.com/api/stock/{ticker}/finance/annual"

    try:
        # 현재가 조회
        r_basic = requests.get(basic_url, headers=headers, timeout=5)
        if r_basic.status_code != 200:
            return None
        basic_data = r_basic.json()
        close_price = str(basic_data.get("closePrice", "0")).replace(",", "")
        price = int(close_price) if close_price.isdigit() else 0

        # 페니주 필터링 (주가 3,000원 미만 제외)
        if price < 3000:
            return None

        # 연간 재무제표 조회
        r_fin = requests.get(finance_url, headers=headers, timeout=5)
        if r_fin.status_code != 200:
            return None
        fin_data = r_fin.json()

        fin_rows = fin_data.get("financeInfo", {}).get("rowList", [])
        op_profits, debt_ratios, pers = [], [], []

        for row in fin_rows:
            title = row.get("title", "")
            cols = row.get("columns", [])
            vals = []
            for col in cols:
                v = str(col.get("value", "")).replace(",", "")
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    continue

            if "영업이익" in title:
                op_profits = vals
            elif "부채비율" in title:
                debt_ratios = vals
            elif "PER" in title:
                pers = vals

        # 2개년치 영업익, 최신 부채비율, 최신 PER 필수
        if len(op_profits) < 2 or not debt_ratios or not pers:
            return None

        prev_op = op_profits[-2]
        curr_op = op_profits[-1]
        debt_ratio = debt_ratios[-1]
        per = pers[-1]

        # 적자 기업 및 음수 PER 배제
        if prev_op <= 0 or curr_op <= 0 or per <= 0:
            return None

        growth_rate = ((curr_op - prev_op) / prev_op) * 100
        if growth_rate <= 0:
            return None

        peg = per / growth_rate

        # 린치 기준 충족 여부: PEG < 1.0, 영업익성장 15% 이상, 부채비율 100% 이하
        is_pass = (peg < 1.0) and (growth_rate >= 15.0) and (debt_ratio <= 100.0)

        if is_pass:
            return {
                "ticker": ticker,
                "name": name,
                "market": market_type,
                "price": price,
                "per": round(per, 2),
                "growth": round(growth_rate, 2),
                "peg": round(peg, 2),
                "debt_ratio": round(debt_ratio, 2)
            }
    except Exception:
        return None
    return None

# ==========================================
# 3. 메인 실행 루틴
# ==========================================
def main():
    print("국내 유니버스 수집 중 (코스피 200 + 코스닥 300)...")
    targets = get_target_tickers()
    print(f"총 {len(targets)}개 종목 대상 피터 린치 스크리닝 시작...")

    passed_stocks = []
    scanned_count = 0

    # ThreadPool을 활용한 고속 병렬 스크리닝
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(check_peter_lynch_kr, t[0], t[1], t[2]): t for t in targets}
        for future in as_completed(futures):
            scanned_count += 1
            res = future.result()
            if res:
                passed_stocks.append(res)

    # PEG가 낮은 순(성장률 대비 가장 저평가된 순)으로 정렬
    passed_stocks.sort(key=lambda x: x['peg'])
    total_count = len(passed_stocks)

    # ==========================================
    # 텔레그램 메시지 발송
    # ==========================================
    msg = f"📖 *[피터 린치 Agent - 한국 저평가 고성장주]*\n"
    msg += f"• **검사 대상**: 상위 {scanned_count}개 종목 (코스피 200 + 코스닥 300)\n"
    msg += f"• **통과 종목**: 총 {total_count}개 포착\n"
    msg += "• **선별 기준**: `PEG < 1.0` + `영업익 성장률 ≥ 15%` + `부채비율 ≤ 100%`\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if passed_stocks:
        for idx, s in enumerate(passed_stocks[:20], 1):
            peg_badge = "🔥 초우수" if s['peg'] <= 0.5 else "✨ 우수"
            msg += f"*{idx}위. {s['name']}* (`{s['ticker']}` / {s['market']}): {s['price']:,}원\n"
            msg += f"   • **PEG**: `{s['peg']}` ({peg_badge})\n"
            msg += f"   • 실적: PER `{s['per']}배` / 영업익 성장: `+{s['growth']}%`\n"
            msg += f"   • 재무: 부채비율 `{s['debt_ratio']}%`\n\n"
        
        msg += "👉 *실전 전략*: 차트상 200일선 아래에 머물러 미네르비니 템플릿에 걸리지 않더라도, 펀더멘털 성장 대비 주가가 눌려 있는 턴어라운드/선취매 슬롯으로 분할 진입을 고려하십시오."
    else:
        msg += "ℹ️ 유니버스 500개 중 린치의 엄격한 저평가 고성장 기준을 통과한 종목이 없습니다."

    print(f"스크리닝 완료: {total_count}개 종목 검출. 텔레그램 전송 중...")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
