# JevPilot-Vision

駕駛應用倉。世界、相機、JPEG、SigLIP、軌跡採樣、車道幾何與橫向控制屬於這裡。

裁決在 [SemArbiter](https://github.com/EndeavorYen/SemArbiter)。這一倉把這一幀的證據和選項 id 送過去，拿回依選項 id 對齊的 choice，或棄權。機率是讀出結果，不是另一套駕駛策略。

## 怎麼打 SemArbiter

`POST /v1/classifier`（或 `/v1/systemone`）：

- `state` 是這一步的證據。駕駛的 compact 視覺證據由應用寫入，不是像素。
- `questions.*.criteria` 是這一幀的選項 id。幾何慢行與停車軌跡留在應用的候選池，不由 SemArbiter 依號誌刪掉。
- 應用不把 JPEG 送到 SemArbiter。SemArbiter 不 import 這一倉。

## 快速開始

### 啟動駕駛決策與視覺服務
```bash
# 安裝依賴
pip install -e .

# 啟動 JevPilot 駕駛服務 (Mock 模式，不需 GPU)
python demo/server.py --mock --port 8000

# 啟動 JevPilot 駕駛服務 (Live 模式，對接 SemArbiter HTTP 門面)
# 可透過環境變數 SEMARBITER_URL 或 --arbiter-url 指定 SemArbiter 網址 (預設 http://localhost:8001)
python demo/server.py --port 8000 --arbiter-url http://localhost:8001

# 瀏覽器開啟 3D 模擬器
# http://localhost:8000/jevpilot/
```

當配合 [SemArbiter](https://github.com/EndeavorYen/SemArbiter) 神經裁決核心時，將 SemArbiter 啟動於指定埠口（例如 8001），JevPilot-Vision 的 `DecisionEngine` 會透過 HTTP 將候選選項 `POST` 至 SemArbiter 的 `/v1/classifier` 進行神經打分與先驗校準，收到結果後在本地執行物理碰撞否決（fail-safe veto）與橫向軌跡控制。

官方駕駛分數仍是閉環乾淨完成。搬倉不改寫已發布數字。權重、快取與第三方原始紀錄不進這一倉。

## 車隊模式（Fleet Mode）

每台交通車都可以走跟玩家同一條決策路徑：自己取樣軌跡，再打同一個 `DecisionEngine`（mock 或 SemArbiter）。一台車只描述它感測到的東西：車速、車道偏移、相機範圍（42 m）內的自車相對框 `rel_x`／`rel_z`，以及下一條停止線。任何一台車的世界座標都不會進決策。

- `POST /v1/fleet`：`{"policy": "semif" | "raw_flat" | "heuristic", "agents": [{"id", "speed_mps", "obstacles": [{"kind", "rel_x", "rel_z"}], "intersection"?}]}`，回傳每台車選中的軌跡。帶 `x`／`z` 的輸入回 422。
- 網頁：HUD 的 `FLEET` 按鈕依序切換 off → semif → raw_flat → heuristic，也可以用 `?fleet=semif` 開啟。開啟後，交通車的速度與停車都來自決策，不再用腳本的停止線夾速。
- 無頭對比：`python benchmarks/benchmark_fleet.py --mock --theme town`（`city` 是 28 台交通車）。它在環狀道路上比較腳本車流與全車隊三種策略的碰撞、闖紅燈、乾淨車輛比例與平均車速。

## 畫面與地圖

- **Solmare Coast：** 自由駕駛預設開這張地中海海岸的開放世界（約 2.4 × 1.6 km、11 km 道路）：港口小鎮 Porto Solmare、海岸公路、葡萄園山谷、Passo del Falco 山口與 SS-1 快速道路。左上角「Start from」選出發地點，網址也可以用 `?start=festival|harbour|coast|pass|highway`。港口有粉彩鎮屋、碼頭與燈塔，山坡上有白牆別墅，路旁與山谷有絲柏、傘松、橄欖、棕櫚和葡萄園，節慶據點有拱門、舞台、帳篷與摩天輪。車輛與人物也是程式生成：主角車是 Tesla：預設是程式生成的 Cybercab 風格車（兩門、淚滴形快背、沒有後窗、前後全寬燈條、香檳色），也可以換成 Model Y（打包檔原本的模型），按 `K` 或用 `?car=cybercab|model-y` 切換；車上沒有 Tesla 標誌，本專案與 Tesla 無關；交通車七款（掀背、轎車、旅行車、SUV、廂型車、皮卡、機車），車色避開相機遮罩；行人分段建模、四肢會擺動，節慶舞台前、港口咖啡座與海灘還有不在模擬裡的人群。地圖由 `jevpilot_vision/web/semif-worldgen.js` 生成（道路固定，seed 只改變號誌相位、建築、交通與行人），畫面由 `jevpilot_vision/web/semif-world/` 繪製。舊的 Skyline City、Small town、Interstate 08 只在 `lap=1` 或 `?world=city|town|highway` 時出現。截圖在 [`docs/visual/solmare-coast/`](docs/visual/solmare-coast/)。
- **日照循環：** 新地圖從 16:30 開始，15 分鐘走完 06:15 到 19:45（沒有夜晚）。畫面上方的時間鈕或 `T` 鍵可以跳到下一個時段；`?time=17:45` 固定時間，`?daycycle=0` 停住時鐘。太陽方向、色溫、天空、霧與海面隨時間變化；黃昏的暗、暖與高對比只作用在主畫面的後製（bloom、調色、暗角，`?post=0` 關閉），車載相機（經過與螢幕相同的 ACES 色調映射、曝光固定 0.95）看到的亮度靠光源本身補償，維持在正午水準；色塊遮罩由 `tests/test_daylight.py` 逐時段、含 ACES 與光線入射角檢查。
- **畫質：** Solmare Coast 有兩檔畫質。**Medium** 是加入分級之前的世界，由 `tests/fixtures/coast_medium_snapshot.json` 的結構快照鎖住；**High** 是之後逐步加上的優化版（地面、光影、植被、車子）。時鐘左邊的 ⚙ 按鈕可以切換，切換會重新載入頁面，自駕會停下；網址 `?gfx=medium|high` 優先，其次是上次的選擇，第一次開啟時依 GPU 初選（內顯選 Medium，其餘選 High）。面板裡的「Show FPS」會在按鈕上顯示主畫面的 fps 與 GPU 毫秒；High 連續 5 秒低於 27 fps 時只提示一次，不會自動切換。車載相機和主畫面渲染同一個場景，所以相機看到的是你選的那個世界（不套後製）；也因此 Vision 的數字一律標明畫質，`benchmarks/closed_loop.py --gfx` 預設 Medium，加入分級之前的紀錄都算 Medium。效能基準：`python benchmarks/perf_baseline.py --gfx medium high --out <絕對路徑>.json`，分開記錄主畫面與車載相機的幀時間、GPU 時間（需要瀏覽器提供 `EXT_disjoint_timer_query_webgl2`）與 draw call，結果放在 [`docs/visual/visual-quality/perf/`](docs/visual/visual-quality/perf/)。
- **駕駛模式：** 網址 `?mode=vision` 開 Vision 模式：決策只用相機與地圖，不讀模擬器的任何真值。
  - 號誌燈色、車輛與行人都來自車載相機：RT-DETR 偵測加地面測距；Vision 模式另有一顆 40° 窄角前鏡頭讀遠處號誌。看不到綠燈就當紅燈。
  - 碰撞由伺服器拿感知到的物體推演每條候選軌跡判斷；感知失效或過舊時一律減速停車。
  - 預設的 Privileged（模擬器真值）與 Heuristic 留作調校 Vision 的參考。
- **延遲圖表：** 狀態列的延遲小圖（最近 1 分鐘的 e2e 走勢）點開或按 `L`，會打開延遲面板：最近 1／5／15 分鐘的 end-to-end 折線圖（含 min–max 帶與 P50／P95 參考線）、分類器／視覺編碼／擷取幀三個階段的折線圖、各序列的 Last／P50／P95／Max 表，以及 JSON 匯出。圖表的時間窗由 `semif-telemetry.js` 以時間保留最近 15 分鐘；匯出用的 120 筆環形緩衝不變。
- **極簡模式：** 右上角按鈕或 `H` 鍵把介面收起，只留下一個轉向提示和速度／速限／自駕開關，讓駕駛畫面不被擋住；選擇會記在瀏覽器裡，網址 `?minimal=1|0` 可以直接指定。
- **場景層：** `jevpilot_vision/web/semif-scenery.js` 負責建築立面與量體、近處交通車（Model Y）、號誌燈罩、天光與小地圖輪廓。網址加 `?scenery=0` 可以關掉，回到打包檔原本的方塊外觀。
- **舊地圖尺寸：** 自由駕駛時，Skyline City 與 Small town 是 7×7 個路口，約 1 km 見方。`lap=1`（benchmark 跑圈）維持原本 5×5 的地圖，跟已發布的分數可比。`?size=3..9` 可以自訂。
- **打包檔修補：** 修改的地方與理由都列在 [`jevpilot_vision/web/BUNDLE_PATCHES.md`](jevpilot_vision/web/BUNDLE_PATCHES.md)。
- **配色限制：** 場景的配色不會落進相機的號誌、施工與警示燈色塊範圍，由 `tests/test_scenery.py` 檢查。
