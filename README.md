# LLM 市場三圖儀表板

GitHub Pages：部署後見 repo 的 Settings → Pages（預設網址為 `https://<owner>.github.io/<repo>/`）。

三張圖：
1. SDLLMTK 價格（USD / 百萬 tokens）
2. OpenRouter 各品牌 Token 使用量（billion tokens，日／週）
3. 價格 × 用量支出 proxy（USD / 天）

## 資料來源

- SDLLMTK 價格：Silicon Data public embed（`portal.silicondata.com/token-index-chart`），每天更新
- OpenRouter 用量：OpenRouter Datasets API（`openrouter.ai/api/v1/datasets/rankings-daily`），每週一更新

## 自動更新（你不用記時間）

GitHub Actions 檔：`.github/workflows/update-dashboard.yml`
- **每天台灣時間 08:40**（UTC 00:40）：更新 SDLLMTK 單價（跟官方公開窗口走；官方晚一天，圖就晚一天）
- **每週一台灣 08:40**：再抓 OpenRouter 用量 + 單價

成功後會自動 commit `index.html` 與價格 CSV，Pages 跟著更新。手動也可：Actions → **update-dashboard** → **Run workflow**。

## 必要 Secret

Repo → Settings → Secrets and variables → Actions：

| Name | 用途 |
|------|------|
| `OPENROUTER_API_KEY` | 週一／手動抓 OpenRouter 用量 |

## 手動觸發

Repo → Actions → update-dashboard → Run workflow（完整更新）。

## 本機腳本（相對本 repo）

- `scripts/update_market_triple.py`：產生儀表板
- `scripts/fetch_openrouter_daily.py`：抓 OpenRouter 用量（需環境變數 `OPENROUTER_API_KEY`）
