# 小學教席 · 每日自動更新 ✿（雙來源）

每日自動抓取 **兩個來源** 的小學教席，篩走助理 / 工友 / IT / 幼稚園 / 校長 / 純中學，
合併去重後輸出 `jobs.json`，以可愛文青風頁面 `index.html` 顯示最新一批。GitHub Actions 免費排程，零伺服器。

**來源**
1. **明報 JUMP** 教育類 —— 逐頁分頁，乾淨穩定（`scraper.py`）
2. **香港教席網 hktpost** —— 聚合站（已整合 Jump + jobsdb），附 **地區 / 資助類型 / 語言 / 宗教** 等資料（`hktpost.py`）

兩來源會**合併去重**（同校同職位只留一個，並記低出現於邊個來源；hktpost 的地區資料會補入合併結果）。

```
tryeat-primary-jobs/
├── index.html          # 文青版頁面：搜尋 + 科目 + 類型 + 地區 + 來源 篩選，加 ♥ 收藏
├── jobs.json           # 合併後職位資料（爬蟲每日覆寫；附種子 60 個）
├── scraper.py          # 主爬蟲：明報 + hktpost → 分類 → 合併去重 → 寫 jobs.json
├── hktpost.py          # hktpost 來源模組（按科目逐個抓）
├── notify.py           # （可選）有新 job 就發 WhatsApp / webhook 通知
├── requirements.txt
└── .github/workflows/daily.yml   # 每日 07:00 (HKT) 自動跑
```

## 一、本機試跑

```bash
pip install -r requirements.txt
python scraper.py                  # 抓兩個來源，產生 jobs.json
python scraper.py --source hktpost # 只抓香港教席網
python scraper.py --source mingpao # 只抓明報
python scraper.py --debug          # 各來源抓少量並印出，核對解析
python -m http.server 8000         # 然後瀏覽器開 http://localhost:8000
```
> ⚠️ 唔好用「雙擊 index.html」嘅 `file://` 方式開，瀏覽器會擋住讀本地 `jobs.json`。

## 二、部署到 GitHub（每日自動更新）

1. 開新 GitHub repo，把整個資料夾 push 上去。
2. **GitHub Pages**：Settings → Pages → Source `Deploy from a branch` → `main` `/(root)` → Save。
   會得到 `https://<帳號>.github.io/<repo>/`，呢條就係你每日睇嘅報告。
3. **寫入權限**：Settings → Actions → General → Workflow permissions → **Read and write** → Save。
4. 完成。每日香港時間 **07:00** 自動跑；亦可去 Actions 分頁㩒 **Run workflow** 即時觸發。

## 三、（可選）新職位通知

repo → Settings → Secrets → 加 `WHATSAPP_API_URL`（你 bridge 的 send endpoint 或 Slack/Discord webhook）、
`WHATSAPP_TO`（收件人）；再喺 `daily.yml` 移除「Notify new jobs」段的註解。`notify.py` 只喺今日有新職位時發送。

## 四、調整篩選規則

分類規則集中喺 `scraper.py` 上方：`EXCLUDE_RE`（要剔走的）、`PRIMARY_RE`（小學標記）、`SPECIAL_RE`（特殊學校）。
想連「小學教學助理」一齊收？把 `教學助理|助理教師` 由 `EXCLUDE_RE` 移走即可。
hktpost 要抓邊啲科目，改 `hktpost.py` 內的 `SUBJECTS` 清單。

## 五、注意事項與已知限制

- **hktpost 已用官方 load_more API 翻到底**：每科目由首頁取首 10 個，再呼叫
  `?...&api=load_more&loaded_posts=N`（N 每次 +10）逐批攞，直到回傳空為止
  （每科安全上限 600 個）。所以兩個來源而家都做到**盡量抓晒**。
- 兩個網站都無正式公開文件，靠解析 HTML / 片段。若改版，調整 `parse_listing()`（明報）/
  `parse_hktpost()`（hktpost）的選擇器；先用 `--debug` 睇結構。校名 / 地區屬啟發式擷取，個別職位請點連結核對。
- 請有禮貌咁爬（已設每批延遲、合理 User-Agent、每日一次）；使用前請尊重兩站的 `robots.txt` 與服務條款，本工具只作個人求職用途。
