import os
import requests
import pandas as pd
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_kr_financials(code: str):
    """네이버 금융 기업개요 및 주요재무제표 크롤링"""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    try:
        # 현재가
        price_tag = soup.select_one(".no_today .blind")
        price = int(price_tag.text.replace(",", "")) if price_tag else 0

        # 종목명
        name_tag = soup.select_one(".wrap_company h2 a")
        name = name_tag.text if name_tag else code

        # 재무제표 테이블 (최근 연간/분기 실적)
        finance_table = pd.read_html(r.text, attrs={"class": "tb_type1 tb_num tb_type1_ifrs"})[0]
        finance_table.set_index(finance_table.columns[0], inplace=True)

        # 당기순이익/영업이익 및 부채비율, PER 행 추출
        # (테이블 구조상 최근 분기/연간 데이터 위치 파싱)
        op_profit_row = finance_table.loc["영업이익"]
        debt_ratio_row = finance_table.loc["부채비율"]
        per_row = finance_table.loc["PER(배)"]

        # 직전 연도 대비 영업이익 증가율 추산
        prev_op = float(op_profit_row.iloc[1])
        curr_op = float(op_profit_row.iloc[2])
        growth_rate = ((curr_op - prev_op) / abs(prev_op)) * 100

        per = float(per_row.iloc[2])
        debt_ratio = float(debt_ratio_row.iloc[2])

        if growth_rate <= 0 or per <= 0:
            return None

        peg = per / growth_rate

        # 린치 기준: PEG < 1.0, 부채비율 < 100%, 영업이익 성장 15% 이상
        if peg < 1.0 and growth_rate >= 15 and debt_ratio <= 100:
            return {
                "code": code,
                "name": name,
                "price": price,
                "per": round(per, 2),
                "growth": round(growth_rate, 2),
                "peg": round(peg, 2),
                "debt_ratio": round(debt_ratio, 2),
            }
    except Exception:
        return None

def run_kr_agent(code_list):
    hits = []
    for code in code_list:
        res = get_kr_financials(code)
        if res:
            hits.append(res)

    if not hits:
        return

    msg = "🇰🇷 *[피터 린치 Agent - 한국 유망주 포착]*\n\n"
    for item in hits:
        msg += f"• *{item['name']} ({item['code']})*\n"
        msg += f"  - 주가: {item['price']:,}원\n"
        msg += f"  - PEG: `{item['peg']}` (PER: {item['per']} / 영업이익 성장: {item['growth']}벽%)\n"
        msg += f"  - 부채비율: `{item['debt_ratio']}%`\n\n"

    send_telegram_alert(msg)

if __name__ == "__main__":
    # 코스피/코스닥 중소형주 및 관심 종목 풀
    kr_universe = ["005930", "000660", "247540", "041510", "035900", "028300"]
    run_kr_agent(kr_universe)
