# AGENTS.md

給在這個 repo 工作的 agent（Claude Code、Codex 等）。這些是專案擁有者的要求，優先於 agent 的預設做法。

## 世界與感知

- **錯的不是世界，是我們。** 不為了讓車上感知讀得懂而改世界（燈色、燈的形狀、多加號誌頭、配色、版面）。感知讀不懂時，改的是感知：演算法、感測器、時序推理、地圖先驗。改車上的感測器（例如加一顆窄角相機）可以。
- 過去為感知改過的世界由 #30 撤回；在那之前不要再加新的。

## 三種駕駛模式

- **Privileged**：決策讀模擬器的狀態表（車、燈、衝突的真值）。要評決策模型時，用它當消融基準。
- **Vision**（`?mode=vision`）：動態物件與號誌只來自車上相機，連碰撞判斷都用相機看到的物體，完全不讀模擬器真值。它回答的是「沒有物件與號誌的真值，閉環能不能關起來」，不是「比 upstream 更正確」。
- **Heuristic**：幾何基準。
- Privileged 與 Heuristic 保留作為參考，用來學習與調校 Vision。
- 講 Vision 時要說清楚邊界：
  - 地圖（路網、車道、路線、建築）仍是特權資訊。
  - 自車定位（車道橫向偏移、到停止線的距離、路線誤差）是模擬器的完美定位，不是估計值。
  - Vision 的本地否決和感知共用同一個失效來源（偵測器漏掉的車，否決也會漏掉）。
  - 感知方法（RT-DETR、已知相機高度、平地測距、色相讀燈）只在這個渲染器成立，不能當成可轉移的證據。
  - mock 裁決器的結果是「mock + 這套感知」，不是任何決策模型的成績。
- 「幾何、候選軌跡、碰撞預測、安全煞車留在本地，模型只挑選項 id 或棄權」這個契約來自 upstream，說明時要歸功 upstream。

## 不能動的東西

- 舊地圖（Skyline City、Small town、Interstate 08）與 `lap=1` 的行為和已發布的分數要維持可比；新行為只放在 coast 地圖或明確的模式之下。
  - 如果修正無法避免改變舊地圖的結果（例如 #55 拿掉吃規劃器亂數的死碼），要先經擁有者同意。合併後重跑 seed 42 的兩趟官方分數（`benchmarks/web_city_vision.py`），新舊並列，並寫明差異的原因。
- 打包檔（`jevpilot_vision/web/assets/`）只能用精確、只出現一次的字串替換來改。每個補丁都要登記在 `tests/test_coast_patches.py` 的 `COAST_PATCHES`，並寫進 `jevpilot_vision/web/BUNDLE_PATCHES.md`；改了資產就要同步調整 `?v=` 版本號。
- `tests/test_trajectory_sampler.py` 的研究契約：號誌不進入候選路徑產生器，`VECTOR_INSTRUCTIONS` 裡不教模型停車。

## 評估

- 調參用的 seed 和驗收用的 seed 要分開；驗收 seed 不拿來除錯。
- 回報發生率與次數（例如「闖紅燈 2/30」），不要用少數幾趟就說「乾淨」。
- 從單一機器、單一地圖量到的常數（決策間隔、減速度、距離上限）要標明出處；能從量測或地圖推得的，就不要寫死。
- 每個修正都要附證據：修之前在驗收集失敗、修之後通過。

## 流程

- 每件事都是一個 issue：先在 issue 上留簡短的 brief，再從 main 開分支，用 TDD 實作。
- 發 PR 前做 pre-submit review：範圍超過 light tier 時，由新的 subagent 跑 `open-code-review-delegate`。Critical / High 要修掉才能送出。
- PR 寫 `Closes #N`；用 `gh pr merge N --merge --match-head-commit <SHA>` 合併在確切的 head 上。
- 進度記在 repo 根目錄的 `PROGRESS.md`（不 commit）。
- 瀏覽器測試用 chrome-cdp-ex（背景模式，`CDP_PORT=9222`）。同一時間只開一個 jevpilot 分頁，因為伺服器的 vision 槽位是共用的。
- 對使用者的回覆、issue 與 PR 用繁體中文；程式碼、識別字與 commit 訊息照原本的慣例。
- 視覺是重點：介面與世界的改動要附截圖。
