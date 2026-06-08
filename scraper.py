#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小學教席每日爬蟲（雙來源）
==================================
來源 1：明報 JUMP 教育類（逐頁分頁，乾淨）
來源 2：香港教席網 hktpost（聚合 Jump + jobsdb，附地區 / 資助等資料；見 hktpost.py）

流程：兩個來源各自抓取 → 統一「小學教席」分類過濾（剔走助理 / 工友 / IT /
幼稚園 / 校長 / 純中學）→ 合併去重（同校同職位只留一個，記低來源）→ 寫 jobs.json，
並與昨日比對標記「新出」。

用法:
    python scraper.py                 # 抓兩個來源，寫 jobs.json
    python scraper.py --source mingpao  # 只抓明報
    python scraper.py --source hktpost  # 只抓香港教席網
    python scraper.py --debug         # 各來源抓少量並印出，方便核對選擇器
    python scraper.py --max-pages 30  # 限制明報最多抓幾頁
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

import hktpost  # 第二來源

# ----------------------------------------------------------------------
BASE_URL = "https://jump.mingpao.com/job/search"
AREA_ID = "10-0"
DETAIL_BASE = "https://jump.mingpao.com/job/detail/Jobs/2/"
OUTFILE = Path(__file__).parent / "jobs.json"

MAX_PAGES = 80
REQUEST_DELAY = 2.0
TIMEOUT = 20
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; TryEat-PrimaryJobBot/1.0; "
                   "daily primary-teaching-jobs digest)"),
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}

# ---------- 分類規則（兩來源共用）----------
EXCLUDE_RE = re.compile(
    r"教學助理|助理教師|教師助理|助教|教員助理|課室助理|學校發展助理|工友|校工|技工|"
    r"實驗室|實驗員|資訊科技技術員|資訊科技員|IT技術|電腦技術|技術員|文員|文書|書記|"
    r"秘書|校務|會計|出納|採購|幼稚園|幼兒|託兒|nursery|kindergarten|教練|聯課|"
    r"課外活動|活動助理|ACO|\bSEO\b|教育助理|\bEA\b|生活指導|宿舍|舍監|牧民|校巴|"
    r"司機|清潔|保安|admin|clerk|receptionist|接待|校長|principal|社工|輔導員|行政助理",
    re.I,
)
PRIMARY_RE = re.compile(r"小學|小學部|APSM|PSMCD|小學學位教師|助理小學學位教師|primary", re.I)
SPECIAL_RE = re.compile(
    r"特殊|盲|視障|聾|聽障|弱聽|匡智|弱智|智障|嚴重學習|中度|輕度智障|肢體傷殘|"
    r"群育|醫院學校|啓聾|啟聾|心光|展能|自閉|嚴重智障")
DATE_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})")


def make_tags(text, cat, is_new):
    tags = []
    if re.search(r"常額", text): tags.append("perm")
    if re.search(r"合約", text): tags.append("contract")
    if re.search(r"NET|外籍英語|native[- ]speaking", text, re.I): tags.append("net")
    if re.search(r"圖書館|librarian", text, re.I): tags.append("lib")
    if cat == "sp": tags.append("sp")
    if is_new: tags.append("new")
    return tags


def guess_subject(text):
    subj = []
    for label, pat in [
        ("英文", r"英文|english|外籍英語"), ("中文", r"中文|普教中|普通話"),
        ("數學", r"數學|數"), ("音樂", r"音樂"), ("視藝", r"視藝|視覺藝術"),
        ("體育", r"體育"), ("STEAM/常識", r"steam|stem|常識|科學|電腦|資訊|科技"),
        ("圖書館", r"圖書館|librarian"),
    ]:
        if re.search(pat, text, re.I): subj.append(label)
    if not subj:
        return "各科" if re.search(r"各科", text) else "科目未指定"
    return " / ".join(subj)


def classify(title, school):
    text = f"{title} {school}"
    if EXCLUDE_RE.search(text):
        return False, None
    # hktpost 已過濾為小學 level；明報則靠關鍵字判斷
    if not PRIMARY_RE.search(text):
        return False, None
    cat = "sp" if SPECIAL_RE.search(text) else "main"
    return True, cat


# ---------- 明報 JUMP ----------
def parse_listing(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs, seen = [], set()
    for a in soup.select('a[href*="/job/detail/"]'):
        href = a.get("href", "")
        m = re.search(r"(HS\d+)", href)
        if not m: continue
        jid = m.group(1)
        if jid in seen: continue
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 3: continue
        card = a
        for _ in range(5):
            if card.parent is None: break
            card = card.parent
            if len(card.get_text(" ", strip=True)) > len(title) + 6: break
        ct = card.get_text("\n", strip=True)
        school = ""
        for ln in [x.strip() for x in ct.split("\n") if x.strip()]:
            if ln == title or DATE_RE.search(ln) or ln.startswith("HK$"): continue
            if len(ln) >= 3: school = ln; break
        d = ""
        dm = DATE_RE.search(ct)
        if dm:
            y, mo, da = dm.groups(); d = f"{int(y):04d}-{int(mo):02d}-{int(da):02d}"
        jobs.append({"id": jid, "title": title, "school": school, "date": d,
                     "url": DETAIL_BASE + jid})
        seen.add(jid)
    return jobs


def fetch_page(session, page):
    r = session.get(BASE_URL, params={"JobAreaID[]": AREA_ID, "Page": page},
                    headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def scrape_mingpao(max_pages, prev_ids, today, debug=False):
    session = requests.Session()
    out = {}
    empty = 0
    for page in range(1, max_pages + 1):
        try:
            html = fetch_page(session, page)
        except Exception as e:
            print(f"[warn] 明報 page {page} 失敗: {e}"); break
        raw = parse_listing(html)
        if debug:
            print(f"明報 page {page}: {len(raw)} 個連結"); 
            for j in raw[:6]: print("   ", j["school"], "|", j["title"])
            break
        kept = 0
        for j in raw:
            keep, cat = classify(j["title"], j["school"])
            if not keep: continue
            text = f"{j['title']} {j['school']}"
            is_new = j["id"] not in prev_ids
            out[j["id"]] = {
                "t": j["title"], "s": j["school"] or "（未能解析校名，請點連結）",
                "sub": guess_subject(text), "d": j["date"] or today,
                "tags": make_tags(text, cat, is_new), "u": j["url"], "cat": cat,
                "id": j["id"], "src": "mingpao", "area": "", "fund": "",
                "first_seen": today if is_new else None,
            }
            kept += 1
        print(f"明報 page {page}: 命中 {kept}，累計 {len(out)}", file=sys.stderr)
        empty = empty + 1 if not raw else 0
        if empty >= 2: break
        time.sleep(REQUEST_DELAY)
    return out


# ---------- hktpost ----------
def scrape_hktpost_classified(prev_keys, today, debug=False):
    raw = hktpost.scrape_hktpost(debug=debug)
    out = {}
    for j in raw:
        keep, cat = classify(j["title"], j["school"])
        if not keep: continue
        text = f"{j['title']} {j['school']}"
        # hktpost 無穩定 id，用 school+title 做 key
        key = "hk:" + re.sub(r"\s+", "", j["school"] + j["title"])
        is_new = key not in prev_keys
        out[key] = {
            "t": j["title"], "s": j["school"], "sub": guess_subject(text),
            "d": j.get("date") or today, "tags": make_tags(text, cat, is_new), "u": j["url"],
            "cat": cat, "id": key, "src": "hktpost",
            "area": j.get("area", ""), "fund": j.get("fund", ""),
            "first_seen": today if is_new else None,
        }
    return out


# ---------- 合併去重 ----------
def norm_key(rec):
    """跨來源去重鍵：校名 + 職位核心字（去空白 / 標點）。"""
    s = re.sub(r"[\s（）()／/、,，.。-]", "", rec["s"])
    t = re.sub(r"[\s（）()／/、,，.。-]", "", rec["t"])
    return s + "|" + t


def merge(mingpao, hkt):
    merged = {}
    for rec in list(mingpao.values()) + list(hkt.values()):
        k = norm_key(rec)
        if k not in merged:
            rec["sources"] = [rec["src"]]
            merged[k] = rec
        else:
            ex = merged[k]
            if rec["src"] not in ex["sources"]:
                ex["sources"].append(rec["src"])
            # 補回對方有而自己無嘅資料（例如 hktpost 嘅地區）
            for f in ("area", "fund"):
                if not ex.get(f) and rec.get(f): ex[f] = rec[f]
            for tg in rec["tags"]:
                if tg not in ex["tags"]: ex["tags"].append(tg)
    return list(merged.values())


def load_previous():
    if not OUTFILE.exists(): return set(), set()
    try:
        prev = json.loads(OUTFILE.read_text("utf-8"))
        ids = {j["id"] for j in prev.get("jobs", []) if j.get("src") == "mingpao"}
        keys = {j["id"] for j in prev.get("jobs", []) if j.get("src") == "hktpost"}
        return ids, keys
    except Exception:
        return set(), set()


def run(max_pages, source="both", debug=False):
    today = dt.date.today().isoformat()
    prev_ids, prev_keys = load_previous()

    mingpao = scrape_mingpao(max_pages, prev_ids, today, debug) if source in ("both", "mingpao") else {}
    hkt = scrape_hktpost_classified(prev_keys, today, debug) if source in ("both", "hktpost") else {}
    if debug:
        print("\n[debug] 完成試抓，未寫檔。"); return

    jobs = merge(mingpao, hkt)
    # 排序：新出置頂，再按日期新到舊
    jobs.sort(key=lambda x: x.get("d", ""), reverse=True)
    jobs.sort(key=lambda x: "new" in x["tags"], reverse=True)

    payload = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "mingpao": "https://jump.mingpao.com/job/search?JobAreaID[]=10-0",
            "hktpost": "https://www.hktpost.com/search/?level=小學&subject=各科",
        },
        "count": len(jobs),
        "new_count": sum(1 for j in jobs if "new" in j["tags"]),
        "by_source": {
            "mingpao": sum(1 for j in jobs if "mingpao" in j.get("sources", [])),
            "hktpost": sum(1 for j in jobs if "hktpost" in j.get("sources", [])),
        },
        "jobs": jobs,
    }
    OUTFILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n✓ 寫入 {OUTFILE.name}：共 {len(jobs)} 個小學教席"
          f"（明報 {payload['by_source']['mingpao']} ・ hktpost {payload['by_source']['hktpost']}），"
          f"新出 {payload['new_count']} 個。")
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--source", choices=["both", "mingpao", "hktpost"], default="both")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    run(a.max_pages, a.source, a.debug)


if __name__ == "__main__":
    main()
