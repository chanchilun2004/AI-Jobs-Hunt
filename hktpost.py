#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hktpost（香港教席網）來源模組
----------------------------------
香港教席網本身係聚合站（已整合 Jump / jobsdb 等），並附帶地區、資助類型、
語言、宗教等結構化資料。本模組按「科目」逐個抓取小學職位列表，解析每張卡片。

注意:
  • 網站列表用無限捲動（AJAX）載入，伺服器首次回傳通常只含頭十幾個職位。
    我哋用「逐科目抓取」嚟換取廣度（每個科目係獨立 URL）。
  • 若要 100% 覆蓋，最穩陣係用佢背後嘅 JSON API：用瀏覽器 DevTools →
    Network 睇捲動時打邊條 endpoint，再喺 fetch_subject() 換成嗰條即可。
  • HTML 結構若改版，調整 parse_hktpost() 內選擇器（先用 --debug 睇）。
"""

import datetime as dt
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote


def parse_recency(text: str) -> str:
    """把『今日 / X小時前 / X天前 / X週前 / X個月前』轉成大約 ISO 日期。"""
    today = dt.date.today()
    if re.search(r"今日|小時前|分鐘前|剛"
                 , text):
        return today.isoformat()
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return (today - dt.timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*週前", text)
    if m:
        return (today - dt.timedelta(days=7 * int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*(?:個)?月前", text)
    if m:
        return (today - dt.timedelta(days=30 * int(m.group(1)))).isoformat()
    return ""

BASE = "https://www.hktpost.com/search/"
LEVEL = "小學"

# 教學相關科目（剔走純興趣班 / 樂器 / 運動細項，保留主科與常見教席）
SUBJECTS = [
    "各科", "中文", "英文", "數學", "視藝", "音樂", "體育", "ICT",
    "常識", "公社", "科學", "人文", "普通話", "NET", "圖書館", "代課",
    "STEM與機械人",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; TryEat-PrimaryJobBot/1.0; "
        "daily primary-teaching-jobs digest)"
    ),
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 20
DELAY = 2.0

# 申請來源連結的文字標籤（用嚟分辨「唔係職位標題」嘅 anchor）
SRC_LABELS = {
    "jump", "jobsdb", "google", "🔎google", "🧭地圖", "地圖",
    "香港教席網", "天主教教育事務處", "教育局", "+其他1則", "+其他2則",
    "追蹤", "已驗證",
}
SCHOOL_URL_RE = re.compile(r"^https?://www\.hktpost\.com/[^/?#]+$")
JOB_HREF_RE = re.compile(r"/post\?id=|/safe_redirect\?")
DISTRICT_RE = re.compile(r"([\u4e00-\u9fa5]{2,4}區)")
FUND_RE = re.compile(r"(資助|直資|官立|私立|按位津貼)")


def subject_url(subject: str) -> str:
    return f"{BASE}?level={quote(LEVEL)}&subject={quote(subject)}"


def fetch_subject(session: requests.Session, subject: str) -> str:
    r = session.get(subject_url(subject), headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def fetch_more(session: requests.Session, subject: str, loaded: int) -> str:
    """呼叫 hktpost 的 load_more API 取下一批（每批約 10 個）。"""
    url = subject_url(subject) + f"&api=load_more&loaded_posts={loaded}"
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _looks_like_school(text: str) -> bool:
    return bool(re.search(r"學校|小學|書院|中學|幼稚園|學院|教育", text)) and len(text) <= 30


def parse_hktpost(html: str, subject: str) -> list:
    """
    解析一頁 hktpost 列表。策略：
      - 順序行走所有 anchor，記住最近一個「學校頁」連結作為當前學校；
      - 遇到職位連結（/post?id= 或 /safe_redirect?），且文字唔係來源標籤，
        當作一個職位；用學校與職位之間嘅文字抽地區 / 資助類型。
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a")
    jobs = []
    cur_school = ""
    cur_school_node = None

    for a in anchors:
        href = a.get("href", "") or ""
        text = a.get_text(" ", strip=True)
        low = text.lower()

        # 學校頁連結
        if SCHOOL_URL_RE.match(href) and _looks_like_school(text):
            cur_school = text
            cur_school_node = a
            continue

        # 職位連結
        if JOB_HREF_RE.search(href) and text and low not in SRC_LABELS \
                and not low.startswith(("🔎", "🧭")) and len(text) >= 4:
            # 抽卡片文字（學校節點到職位節點之間）以取地區 / 資助
            area, fund = "", ""
            ctx = ""
            if cur_school_node is not None:
                node = cur_school_node
                hops = 0
                while node and node is not a and hops < 60:
                    node = node.next_element
                    if isinstance(node, str):
                        ctx += " " + node.strip()
                    hops += 1
            dm = DISTRICT_RE.search(ctx)
            fm = FUND_RE.search(ctx)
            area = dm.group(1) if dm else ""
            fund = fm.group(1) if fm else ""

            # 擷取職位後方文字（申請來源 + 活躍時間）以解析「X天前」
            tail = ""
            node = a
            hops = 0
            while node is not None and hops < 40:
                node = node.next_element
                if isinstance(node, str):
                    tail += " " + node.strip()
                elif getattr(node, "name", None) == "a" and \
                        SCHOOL_URL_RE.match(node.get("href", "") or ""):
                    break
                hops += 1
            date = parse_recency(tail)

            jobs.append({
                "school": cur_school,
                "title": text,
                "url": href if href.startswith("http") else "https://www.hktpost.com" + href,
                "area": area,
                "fund": fund,
                "date": date,
                "subject_hint": subject,
            })

    return jobs


PAGE_SIZE = 10          # 網站每批載入數量
MAX_BATCHES = 60        # 每科安全上限（最多 600 個）


def scrape_subject(session: requests.Session, subject: str, debug: bool = False) -> dict:
    """抓單一科目：先取首頁，再用 load_more 翻到底。回傳 {key: job}。"""
    out = {}

    def absorb(raw):
        added = 0
        for j in raw:
            key = (j["school"], re.sub(r"\s+", "", j["title"]))
            if key not in out:
                out[key] = j
                added += 1
        return added

    # 首批：完整頁面（含學校 metadata）
    try:
        absorb(parse_hktpost(fetch_subject(session, subject), subject))
    except Exception as e:
        print(f"[warn] hktpost {subject} 首頁失敗: {e}")
        return out

    if debug:
        return out

    # 之後用 load_more 翻到底
    loaded = PAGE_SIZE
    for _ in range(MAX_BATCHES):
        try:
            frag = fetch_more(session, subject, loaded)
        except Exception as e:
            print(f"[warn] hktpost {subject} load_more@{loaded} 失敗: {e}")
            break
        raw = parse_hktpost(frag, subject)
        if not raw:                 # 回傳空 → 到底
            break
        absorb(raw)
        loaded += PAGE_SIZE
        time.sleep(DELAY)
    return out


def scrape_hktpost(debug: bool = False) -> list:
    session = requests.Session()
    seen = {}
    for subj in SUBJECTS:
        sub_out = scrape_subject(session, subj, debug=debug)
        for key, j in sub_out.items():
            seen.setdefault(key, j)
        print(f"hktpost · {subj}: 本科 {len(sub_out)} 個，累計 {len(seen)}")
        if debug:
            for j in list(sub_out.values())[:6]:
                print("   ", j["school"], "|", j["title"], "|", j["area"], j["fund"], "|", j.get("date"))
            break
        time.sleep(DELAY)
    return list(seen.values())


if __name__ == "__main__":
    import sys
    res = scrape_hktpost(debug="--debug" in sys.argv)
    print(f"\n共 {len(res)} 個 hktpost 小學職位（未經教席分類過濾）")
