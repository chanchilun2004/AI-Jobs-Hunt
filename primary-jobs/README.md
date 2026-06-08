# 小學教席 · 每日自動更新 ✿

每日自動抓取明報 JUMP 教育類職位，篩出**小學教師**職位（隔走教學助理 / 工友 / IT / 幼稚園 / 純中學），
輸出 `jobs.json`，並以可愛文青風頁面 `index.html` 自動顯示最新一批。靠 GitHub Actions 每日免費排程，零伺服器。

```
tryeat-primary-jobs/
├── index.html          # 文青版頁面（自動讀 jobs.json，含搜尋 / 科目 / 類型篩選 + ♥ 收藏）
├── jobs.json           # 職位資料（由爬蟲每日覆寫；現附 6/4 的 50 個做種子）
├── scraper.py          # 每日爬蟲：抓取 → 篩選 → 寫 jobs.json（會標記新職位）
├── notify.py           # （可選）有新 job 就發 WhatsApp / webhook 通知
├── requirements.txt
└── .github/workflows/daily.yml   # 每日 07:00 (HKT) 自動跑
```

## 一、本機試跑

```bash
pip install -r requirements.txt
python scraper.py            # 產生 / 更新 jobs.json
python -m http.server 8000   # 然後瀏覽器開 http://localhost:8000
```
> ⚠️ 唔好用「雙擊 index.html」嘅 `file://` 方式開，瀏覽器會擋住讀取本地 `jobs.json`。
> 用上面嘅 `http.server`，或部署到 GitHub Pages（見下）就無問題。

`python scraper.py --debug` 只抓第 1 頁並印出解析結果，方便核對。

## 二、部署到 GitHub（每日自動更新）

1. 開一個新 GitHub repo，把成個資料夾 push 上去。
2. **開 GitHub Pages**：repo → Settings → Pages → Source 揀 `Deploy from a branch`，
   branch 揀 `main`、資料夾 `/ (root)` → Save。幾分鐘後會有條固定網址
   `https://<你的帳號>.github.io/<repo名>/`，呢條就係你每日睇嘅報告。
3. **開 workflow 寫入權限**：repo → Settings → Actions → General →
   Workflow permissions 揀 **Read and write permissions** → Save。
   （`daily.yml` 要 commit 更新後嘅 `jobs.json`。）
4. 搞掂。`daily.yml` 會喺每日香港時間 **07:00** 自動跑；亦可去 Actions 分頁
   㩒 **Run workflow** 即時手動觸發一次。

## 三、（可選）新職位 WhatsApp / Webhook 通知

唔想日日開嚟睇？可以一有新 job 就推送俾你：

1. repo → Settings → Secrets and variables → Actions → 加：
   - `WHATSAPP_API_URL`：你嘅發訊 endpoint（例如你 WhatsApp bridge 嘅 REST send；
     或 Slack / Discord incoming webhook）
   - `WHATSAPP_TO`：收件人（視乎 bridge 格式，例如你的號碼）
2. 打開 `.github/workflows/daily.yml`，移除「Notify new jobs」嗰段嘅井號註解。
3. 用 Slack webhook 嘅話，加多個 secret `WHATSAPP_PAYLOAD=slack`（改用 `{"text": ...}` 格式）。

`notify.py` 只會喺**今日有新職位**時發送；通知失敗都唔會令排程紅燈。
（亦可改成 email：把 `notify.py` 換成 SMTP 版即可。）

## 四、調整篩選規則

爬蟲嘅分類規則集中喺 `scraper.py` 上方：
- `EXCLUDE_RE`：要剔走嘅職位（助理 / 工友 / IT / 幼稚園 / 導師…）
- `PRIMARY_RE`：判定為小學嘅標記（小學 / APSM / PSMCD / 小學部…）
- `SPECIAL_RE`：特殊學校標記
想連「小學教學助理」一齊收？把 `教學助理|助理教師` 從 `EXCLUDE_RE` 移走即可。

## 五、注意事項

- 明報無公開 API，靠解析 HTML。若佢哋改版，`scraper.py` 的 `parse_listing()`
  選擇器可能要微調（先用 `--debug` 睇結構）。校名 / 日期解析屬啟發式，個別職位可能要點連結核對。
- 請有禮貌咁爬：腳本已設定每頁延遲、合理 User-Agent、每日一次低頻率。
  使用前請尊重明報嘅 `robots.txt` 同服務條款；本工具只作個人求職用途。
