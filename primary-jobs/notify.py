#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
（可選）新職位通知
------------------
讀 jobs.json，揾出今日標記為「new」（first_seen = 今日）嘅職位，
有就 POST 一條訊息去你指定嘅 webhook。

設計成 generic webhook，適用於：
  • 你自己嘅 WhatsApp bridge（whatsmeow / whatsapp-mcp 多數有 REST send endpoint）
  • Slack / Discord incoming webhook
  • 任何收 JSON {to, message} 嘅 endpoint

環境變數（喺 GitHub repo Settings → Secrets and variables → Actions 設定）:
  WHATSAPP_API_URL   你嘅發訊 endpoint，例如 https://alanworkphone.zeabur.app/api/send
  WHATSAPP_TO        收件人，例如 85291757723（視乎你 bridge 格式）
  WHATSAPP_PAYLOAD   （可選）"slack" 改用 {"text": ...} 格式

若無設定 WHATSAPP_API_URL，腳本會安靜跳過，唔會令 workflow 失敗。
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

JOBS = Path(__file__).parent / "jobs.json"


def main():
    url = os.environ.get("WHATSAPP_API_URL", "").strip()
    if not url:
        print("未設定 WHATSAPP_API_URL，略過通知。")
        return

    to = os.environ.get("WHATSAPP_TO", "").strip()
    style = os.environ.get("WHATSAPP_PAYLOAD", "whatsapp").strip().lower()

    if not JOBS.exists():
        print("無 jobs.json，略過。")
        return

    payload = json.loads(JOBS.read_text("utf-8"))
    today = dt.date.today().isoformat()
    new_jobs = [
        j for j in payload.get("jobs", [])
        if j.get("first_seen") == today or "new" in j.get("tags", [])
    ]
    if not new_jobs:
        print("今日無新職位，唔發通知。")
        return

    lines = [f"🆕 今日新出小學教席 {len(new_jobs)} 個："]
    for j in new_jobs[:15]:
        lines.append(f"• {j['s']}｜{j['t']}（{j.get('sub','')}）\n  {j['u']}")
    if len(new_jobs) > 15:
        lines.append(f"…另外仲有 {len(new_jobs) - 15} 個，開報告睇晒。")
    message = "\n".join(lines)

    if style == "slack":
        body = {"text": message}
    else:
        body = {"to": to, "message": message}

    try:
        r = requests.post(url, json=body, timeout=20)
        r.raise_for_status()
        print(f"✓ 已發送通知（{len(new_jobs)} 個新職位）。")
    except Exception as e:
        # 通知失敗唔應該令整個 workflow 紅燈
        print(f"[warn] 通知發送失敗：{e}", file=sys.stderr)


if __name__ == "__main__":
    main()
