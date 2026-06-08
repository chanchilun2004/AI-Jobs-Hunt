#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
明報 JUMP 小學教席每日爬蟲
----------------------------------
抓取教育類職位列表，篩走助理 / 工友 / IT / 幼稚園 / 純中學職位，
只留「小學教師」職位（PSM / APSM / GM / 科任 / 小學圖書館主任 / 特殊小學教席），
輸出 jobs.json 供前端頁面讀取。

用法:
    python scraper.py                # 正常跑，寫入 jobs.json
    python scraper.py --debug        # 只抓第 1 頁並印出解析結果，方便核對選擇器
    python scraper.py --max-pages 30 # 限制最多抓幾頁

備註:
    本站無公開 API，靠解析 HTML。若明報改版，請調整下方
    parse_listing() 內的選擇器（已盡量寫得寬鬆、抗改版）。
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------
BASE_URL = "https://jump.mingpao.com/job/search"
AREA_ID = "10-0"                     # 教育類
DETAIL_BASE = "https://jump.mingpao.com/job/detail/Jobs/2/"
OUTFILE = Path(__file__).parent / "jobs.json"

MAX_PAGES = 80
REQUEST_DELAY = 2.0                  # 每頁之間禮貌延遲（秒）
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; TryEat-PrimaryJobBot/1.0; "
        "daily primary-teaching-jobs digest; contact: alan@tryeat)"
    ),
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}

# ----------------------------------------------------------------------
# 分類規則（與前端文青版頁面一致）
# ----------------------------------------------------------------------
EXCLUDE_RE = re.compile(
    r"教學助理|助理教師|助教|教員助理|課室助理|工友|校工|技工|實驗室|實驗員|"
    r"資訊科技|IT\s|電腦技術|技術員|文員|文書|書記|秘書|校務|會計|出納|採購|"
    r"幼稚園|幼兒|託兒|nursery|kindergarten|導師|教練|聯課|課外活動|活動助理|"
    r"ACO|\bSEO\b|教育助理|\bEA\b|生活指導|宿舍|舍監|牧民|校巴|司機|清潔|"
    r"保安|admin|clerk|receptionist|接待",
    re.I,
)
# 小學標記（含一條龍中小學、小學部）
PRIMARY_RE = re.compile(
    r"小學|小學部|APSM|PSMCD|小學學位教師|助理小學學位教師|primary",
    re.I,
)
# 特殊學校標記
SPECIAL_RE = re.compile(
    r"特殊|盲|視障|聾|聽障|弱聽|匡智|弱智|智障|嚴重學習|中度|輕度智障|肢體傷殘|"
    r"群育|醫院學校|啓聾|啟聾|心光|展能|自閉|嚴重智障",
)
# 純中學偵測（標題明確只係中學職級而無小學標記時剔走）
SECONDARY_RE = re.compile(r"中學學位教師|\bGM\b|secondary|中學部")

DATE_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})")


def make_tags(text: str, cat: str, is_new: bool) -> list:
    tags = []
    if re.search(r"常額", text):
        tags.append("perm")
    if re.search(r"合約", text):
        tags.append("contract")
    if re.search(r"NET|外籍英語|native[- ]speaking", text, re.I):
        tags.append("net")
    if re.search(r"圖書館|librarian", text, re.I):
        tags.append("lib")
    if cat == "sp":
        tags.append("sp")
    if is_new:
        tags.append("new")
    return tags


def guess_subject(text: str) -> str:
    """從職位文字推斷主要科目，純為顯示用。"""
    subj = []
    for label, pat in [
        ("英文", r"英文|english|外籍英語"),
        ("中文", r"中文|普教中|普通話"),
        ("數學", r"數學|數"),
        ("音樂", r"音樂"),
        ("視藝", r"視藝|視覺藝術"),
        ("體育", r"體育"),
        ("STEAM/常識", r"steam|常識|科學|電腦|資訊|科技"),
        ("圖書館", r"圖書館|librarian"),
    ]:
        if re.search(pat, text, re.I):
            subj.append(label)
    if not subj:
        if re.search(r"各科", text):
            return "各科"
        return "科目未指定"
    return " / ".join(subj)


def classify(title: str, school: str):
    """回傳 (keep: bool, cat: 'main'|'sp')。"""
    text = f"{title} {school}"
    if EXCLUDE_RE.search(text):
        return False, None
    if not PRIMARY_RE.search(text):
        # 無任何小學標記 → 當作非小學（多數係純中學 / 大學 / 行政）
        return False, None
    cat = "sp" if SPECIAL_RE.search(text) else "main"
    return True, cat


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def parse_listing(html: str) -> list:
    """
    從一頁列表 HTML 抽出職位。
    策略：搵所有指向 /job/detail/ 嘅連結，逐個向上爬到所在卡片，
    再喺卡片文字內抽出學校與日期。對 class 名改動有抗性。
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_ids = set()

    anchors = soup.select('a[href*="/job/detail/"]')
    for a in anchors:
        href = a.get("href", "")
        m = re.search(r"(HS\d+)", href)
        if not m:
            continue
        jid = m.group(1)
        if jid in seen_ids:
            continue

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 3:
            continue

        # 向上找卡片容器（最多爬 5 層，揀文字量合理嘅一層）
        card = a
        for _ in range(5):
            if card.parent is None:
                break
            card = card.parent
            txt = card.get_text(" ", strip=True)
            if len(txt) > len(title) + 6:  # 卡片內有額外資訊（學校 / 日期）
                break
        card_text = card.get_text("\n", strip=True)

        # 學校：通常係卡片內另一條連結或公司名；用啟發式 = 卡片首條非標題文字行
        school = ""
        lines = [ln.strip() for ln in card_text.split("\n") if ln.strip()]
        for ln in lines:
            if ln == title:
                continue
            if DATE_RE.search(ln):
                continue
            if len(ln) >= 3 and not ln.startswith("HK$"):
                school = ln
                break

        # 日期
        d = ""
        dm = DATE_RE.search(card_text)
        if dm:
            y, mo, da = dm.groups()
            d = f"{int(y):04d}-{int(mo):02d}-{int(da):02d}"

        jobs.append(
            {
                "id": jid,
                "title": title,
                "school": school,
                "date": d,
                "url": DETAIL_BASE + jid,
            }
        )
        seen_ids.add(jid)

    return jobs


def fetch_page(session: requests.Session, page: int) -> str:
    params = {"JobAreaID[]": AREA_ID, "Page": page}
    r = session.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def load_previous_ids():
    """讀取舊 jobs.json 的 id，用嚟判斷邊啲係新 job。"""
    if not OUTFILE.exists():
        return set()
    try:
        prev = json.loads(OUTFILE.read_text("utf-8"))
        return {j["id"] for j in prev.get("jobs", [])}
    except Exception:
        return set()


def run(max_pages: int, debug: bool = False):
    session = requests.Session()
    prev_ids = load_previous_ids()
    today = dt.date.today().isoformat()

    collected = {}
    empty_streak = 0

    for page in range(1, max_pages + 1):
        try:
            html = fetch_page(session, page)
        except Exception as e:
            print(f"[warn] page {page} 抓取失敗: {e}", file=sys.stderr)
            break

        raw = parse_listing(html)
        if debug:
            print(f"--- page {page}: 解析到 {len(raw)} 個 detail 連結 ---")
            for j in raw[:8]:
                print(json.dumps(j, ensure_ascii=False))
            return

        kept_this_page = 0
        for j in raw:
            keep, cat = classify(j["title"], j["school"])
            if not keep:
                continue
            text = f"{j['title']} {j['school']}"
            is_new = j["id"] not in prev_ids
            collected[j["id"]] = {
                "t": j["title"],
                "s": j["school"] or "（未能解析校名，請點連結查看）",
                "sub": guess_subject(text),
                "d": j["date"] or today,
                "tags": make_tags(text, cat, is_new),
                "u": j["url"],
                "cat": cat,
                "id": j["id"],
                "first_seen": today if is_new else None,
            }
            kept_this_page += 1

        print(f"page {page}: 解析 {len(raw)} 個，命中小學教席 {kept_this_page} 個，"
              f"累計 {len(collected)}", file=sys.stderr)

        # 連續兩頁完全無 detail 連結 → 當作到底
        empty_streak = empty_streak + 1 if len(raw) == 0 else 0
        if empty_streak >= 2:
            break

        time.sleep(REQUEST_DELAY)

    jobs = list(collected.values())
    # 排序：新 job 置頂，再按日期新到舊
    jobs.sort(key=lambda x: ("new" not in x["tags"], x["d"]), reverse=False)
    jobs.sort(key=lambda x: ("new" in x["tags"], x["d"]), reverse=True)

    payload = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": f"{BASE_URL}?JobAreaID[]={AREA_ID}",
        "count": len(jobs),
        "new_count": sum(1 for j in jobs if "new" in j["tags"]),
        "jobs": jobs,
    }
    OUTFILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"✓ 寫入 {OUTFILE.name}：共 {len(jobs)} 個小學教席，"
          f"其中 {payload['new_count']} 個新出。")
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    run(args.max_pages, debug=args.debug)


if __name__ == "__main__":
    main()
