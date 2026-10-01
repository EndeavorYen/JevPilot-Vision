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

- **Solmare Coast：** 自由駕駛預設開這張地中海海岸的開放世界（約 2.4 × 1.6 km、11 km 道路）：港口小鎮 Porto Solmare、海岸公路、葡萄園山谷、Passo del Falco 山口與 SS-1 快速道路。左上角「Start from」選出發地點，網址也可以用 `?start=festival|harbour|coast|pass|highway`。地圖由 `jevpilot_vision/web/semif-worldgen.js` 生成（道路固定，seed 只改變號誌相位、建築、交通與行人），畫面由 `jevpilot_vision/web/semif-world/` 繪製。舊的 Skyline City、Small town、Interstate 08 只在 `lap=1` 或 `?world=city|town|highway` 時出現。截圖在 [`docs/visual/solmare-coast/`](docs/visual/solmare-coast/)。
- **日照循環：** 新地圖從 16:30 開始，15 分鐘走完 06:15 到 19:45（沒有夜晚）。畫面上方的時間鈕或 `T` 鍵可以跳到下一個時段；`?time=17:45` 固定時間，`?daycycle=0` 停住時鐘。太陽方向、色溫、天空、霧與海面隨時間變化；黃昏的暗、暖與高對比只作用在主畫面的後製（bloom、調色、暗角，`?post=0` 關閉），車載相機看到的亮度維持在正午水準，色塊遮罩由 `tests/test_daylight.py` 逐時段檢查。
- **場景層：** `jevpilot_vision/web/semif-scenery.js` 負責建築立面與量體、近處交通車（Model Y）、號誌燈罩、天光與小地圖輪廓。網址加 `?scenery=0` 可以關掉，回到打包檔原本的方塊外觀。
- **舊地圖尺寸：** 自由駕駛時，Skyline City 與 Small town 是 7×7 個路口，約 1 km 見方。`lap=1`（benchmark 跑圈）維持原本 5×5 的地圖，跟已發布的分數可比。`?size=3..9` 可以自訂。
- **打包檔修補：** 修改的地方與理由都列在 [`jevpilot_vision/web/BUNDLE_PATCHES.md`](jevpilot_vision/web/BUNDLE_PATCHES.md)。
- **配色限制：** 場景的配色不會落進相機的號誌、施工與警示燈色塊範圍，由 `tests/test_scenery.py` 檢查。
