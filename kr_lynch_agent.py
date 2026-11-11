import os
import requests
import pandas as pd
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram 미설정 또는 로컬 출력]\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    if res.status_code != 200:
        print(f"Telegram 전송 실패: {res.text}")

def get_kr_financials(code: str):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"[{code}] 페이지 접근 실패 (HTTP {r.status_code})")
            return None
        
        soup = BeautifulSoup(r.text, "html.parser")

        # 1. 종목명 & 현재가 파싱
        name_tag = soup.select_one(".wrap_company h2 a")
        name = name_tag.text.strip() if name_tag else code

        price_tag = soup.select_one(".no_today .blind")
        price = int(price_tag.text.replace(",", "")) if price_tag else 0

        # 2. 재무제표 테이블 파싱
        tables = pd.read_html(r.text, encoding="cp949")
        target_table = None
        for t in tables:
            # 주요재무제표 안내 테이블 탐색
            if any("주요재무정보" in str(col) for col in t.columns) or any("영업이익" in str(idx) for idx in t.iloc[:, 0]):
                target_table = t
                break

        if target_table is None:
            print(f"[{code}] 재무 테이블을 찾을 수 없음")
            return None

        # 첫 번째 열(항목명) 기준 인덱스 설정
        target_table.set_index(target_table.columns[0], inplace=True)
        
        # 텍스트 매칭으로 행 찾기
        op_row = None
        debt_row = None
        per_row = None

        for idx in target_table.index:
            idx_str = str(idx)
            if "영업이익" in idx_str and op_row is None:
                op_row = target_table.loc[idx]
            elif "부채비율" in idx_str and debt_row is None:
                debt_row = target_table.loc[idx]
            elif "PER" in idx_str and per_row is None:
                per_row = target_table.loc[idx]

        if op_row is None or debt_row is None or per_row is None:
            return None

        # 최근 연간 결산 기준 수치 추출 (결측치 및 '-' 필터링)
        def clean_val(val):
            s = str(val).replace(",", "").strip()
            return float(s) if s and s != "-" and s != "nan" else None

        # 최근 연간 2개년치 비교
        prev_op = clean_val(op_row.iloc[1])
        curr_op = clean_val(op_row.iloc[2])
        debt_ratio = clean_val(debt_row.iloc[2])
        per = clean_val(per_row.iloc[2])

        if not all([prev_op, curr_op, debt_ratio, per]):
            return None

        if prev_op <= 0 or curr_op <= 0 or per <= 0:
            return None

        growth_rate = ((curr_op - prev_op) / prev_op) * 100
        if growth_rate <= 0:
            return None

        peg = per / growth_rate

        # 피터 린치 조건: PEG < 1.0, 부채비율 100% 이하, 영업이익 성장률 15% 이상
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
        else:
            print(f"[{name}] 조건 미달: PEG={peg:.2f}, 성장률={growth_rate:.1f}%, 부채비율={debt_ratio:.1f}%")

    except Exception as e:
        print(f"[{code}] 파싱 에러 발생: {e}")
        return None

def run_kr_agent(code_list):
    print("한국장 피터 린치 스크리닝 시작...")
    hits = []
    for code in code_list:
        res = get_kr_financials(code)
        if res:
            hits.append(res)

    if not hits:
        # 조건에 맞는 종목이 없을 때도 텔레그램을 받고 싶다면 아래 주석을 해제하세요.
        # send_telegram_alert("🇰🇷 *[피터 린치 Agent]*\n금일 스크리닝 조건을 만족하는 종목이 없습니다.")
        print("조건 만족 종목 없음.")
        return

    msg = "🇰🇷 *[피터 린치 Agent - 한국 유망주 포착]*\n\n"
    for item in hits:
        msg += f"• *{item['name']} ({item['code']})*\n"
        msg += f"  - 현재가: {item['price']:,}원\n"
        msg += f"  - PEG: `{item['peg']}` (PER {item['per']} / 성장률 {item['growth']}%)\n"
        msg += f"  - 부채비율: `{item['debt_ratio']}%`\n\n"

    send_telegram_alert(msg)

if __name__ == "__main__":
    # 성장률과 저평가 지표가 교차 검증되는 코스피/코스닥 후보군 테스트
    kr_universe = [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "041510",  # 에스엠
        "028300",  # 에이치엘비
        "259960",  # 크래프톤
        "035900",  # JYP Ent.
    ]
    run_kr_agent(kr_universe)
