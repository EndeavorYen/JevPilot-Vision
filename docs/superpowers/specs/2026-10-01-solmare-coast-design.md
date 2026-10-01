# Solmare Coast：全新開放世界地圖與程式生成物件

日期：2026-10-01　狀態：待審

## 1. 目標與成功標準

自由駕駛不再使用打包檔原本的 City／Town／Interstate，改成一張 Forza Horizon 風格的地中海／加州海岸開放世界「Solmare Coast」（虛構地名）。地圖、建築、人物、車輛（含主角車）、植被、小物件全部程式生成。用途是展示：Jev 自駕、vision、SemArbiter 決策在新地圖上照常運作，不加入競速玩法。

成功標準：

1. 截圖呈現 Forza Horizon 的氛圍：午後暖光、海岸、彎道、節慶據點、摩天輪地標。
2. 自駕從節慶據點出發，連續跑完跨區目的地鏈（至少港口、海岸、山口、高速各一次），不撞車、不卡死。
3. 現有 Python 與 node 測試全部通過，`lap=1` 的地圖、路線與分數不變。
4. 1080p、中階顯卡（約 RTX 3060 等級）自由駕駛維持 60 fps。
5. 新增的顏色全部通過相機色塊遮罩測試；沿途抽樣的 vision 幀不出現假的號誌、施工、警示燈色塊。

## 2. 範圍

做：新地圖生成器、新渲染器（地形、海、道路、建築、植被、小物件、人物、車輛、天空與光影）、打包檔補丁、「出發地點」選單、測試、文件與截圖。

不做：計時賽／檢查點等競速玩法、夜晚與天氣、有高度的物理、立體交叉與橋、圓環、音效、手機效能、刪除舊 glb 檔、改動已發布分數。

## 3. 地圖版圖

範圍約 2.4 km × 1.6 km，北為 −z，南側為海。

```
 北  ═══════ SS-1 Costiera 快速道路（雙向四線，100 km/h）═══╦═══════
       ║                                     號誌路口 ║        ╲
   ┌─────┴─────┐      葡萄園山谷        ╭─╮  ╭─╮   Passo del Falco
   │ Porto     │   Via delle Vigne     │ ╰──╯ │  懸崖髮夾彎
   │ Solmare   ├──── S 形彎道 ───┐     ╰╮      ╰─╮
   │ 港口小鎮  │                 │      │ 斷崖   │
   │ 4×3 號誌  │            ★ Horizon 節慶據點    │
   └──┬───┬────┘                                  │
 南 ~~~~~~~~~~ 海岸公路 Lungomare（沿海灣與岬角彎曲）~~~~~~ 海 ~~~~~~
```

- **路網：** 道路是固定設計（seed 只改變號誌相位、建築、交通車與行人，「New layout」重擲的是這些）。全部雙向，組成多個環路，強連通、無死路。路口只有 T 字與十字；港口鎮與節慶區用號誌，山口腳用停車標誌。每條路在路口的最後 25 m 是正南北或正東西的直線（打包檔的轉彎平滑與號誌相位 `Math.abs(Math.cos(approach))>.5` 都以軸向為前提），彎道放在路段中間。所有道路只在路口相交。
- **SS-1 Costiera：** 北側的快速道路，畫成雙向四線，模擬裡每個方向一條車道（內側），外側車道只是畫面。平面世界沒有立體交叉，對向匝道必然穿越另一側車道，所以 SS-1 不做匝道：西端下坡接港口，東端接山口，中間以一個號誌路口連到節慶區，路口前後各 400 m 限速 80 km/h。
- **路邊停車：** 打包檔會把第 2、6 號交通車停在車道上當障礙物，後車不會超車而永久排隊，所以新地圖不產生模擬用的路邊停車；路邊停車改為第 4 期的裝飾物件。
- **限速：** 港口小鎮與節慶區 50 km/h、海岸 80 km/h（彎道處 68–76）、山谷道路 70 km/h（彎道處 59–68）、山口 35 km/h、SS-1 100 km/h。彎道各自是獨立 edge，自駕靠打包檔既有的減速邏輯在彎前降速。限速與彎度須滿足：限速下的側向加速度不超過 3 m/s²。
- **地形：** 路面固定 y=0，路邊 3–6 m 路肩過渡。路肩以外由高度場決定：北側山丘最高約 150 m，山谷兩側起坡，海岸與髮夾彎外側降到約 −12 m 形成斷崖，崖邊設護欄。地形只影響畫面，物理仍是平的。
- **出生與路線：** 自由駕駛預設從節慶據點出發。原「Change map」下拉選單改為「出發地點」：節慶據點、港口、海岸、山口、高速，對應網址 `?start=festival|harbour|coast|pass|highway`。目的地鏈固定為節慶據點 → 港口 → 海岸 → 山口 → 高速 → 節慶據點，從所選出發地點的下一站開始，到達後自動接續下一站。
- **舊地圖：** City／Town／Interstate 只在 `lap=1` 或網址明確寫 `?world=city|town|highway` 時出現，下拉選單不再列出。

## 4. 架構與資料流

```
            ┌──────────── semif-worldgen.js（純函式，不碰 DOM）────────────┐
 seed ────► │ generate(seed) → 打包檔格式的世界 + visual 區塊               │
            └───────┬──────────────────────────────────────┬───────────┘
          主執行緒 <script>                      worker 開頭的靜態 import
                    ▼                                      ▼
      打包檔模擬（物理／號誌／交通／行人）          規劃器 worker（同 seed → 同一張圖）
                    │ build() 時 kit() 交出 THREE 類別
                    ▼
      semif-world/*（新渲染器，掛進打包檔的 scene，共用 renderer 與相機）
```

### 4.1 `web/semif-worldgen.js`

- 以 IIFE 寫成、只用 `globalThis`，主執行緒用 `<script>` 載入，worker 用檔頭 `import "/jevpilot/semif-worldgen.js";` 載入。全域名稱 `globalThis.SEMIF_WORLDGEN`（`SEMIF_WORLD` 已被打包檔的 renderer 佔用）。
- `generate(seed, {start})` 回傳 `type: "coast"` 的世界，欄位與打包檔 `dt()` 相同：`seed, type, theme, nodes, byId, edges, objects, connectorRoads, bounds, startNode, nextNode, destination, route`。
  - 每條 edge 都是雙向，帶 `path`、`centerline` 與 `laneOffset`（一律 3 m，所以在路口直行或經過路段分界點時車道路徑都連續），`kind` 與 `laneHalfWidth` 每條自訂。
  - 路口節點 `townJunction: true`，帶 `control`（`signal`／`stop`）與 `offset`，並產生對應的 `traffic_light`／`stop_sign` 物件（`{nodeId, approach, height}`）。
  - 碰撞用 `building` 物件：只產生離路 25 m 內的建築，維持軸對齊，涵蓋可見量體。
  - 不產生 `roadSamples`；打包檔裡依賴它的地方由補丁改走 `path`。
- 另回傳 `visual`：分區多邊形、地形參數、裝飾物擺放（植被、裝飾人群、船、節慶設施）、人行道路徑（供行人生成）。
- `heightAt(x, z)`：地形高度，地形網格與物件擺放共用。
- 決定性：同一個 seed 輸出逐位元相同；不使用 `Math.random`，只用自帶的 seeded RNG。

### 4.2 `web/semif-world/`（ES modules，依賴只有 `kit.js`）

| 模組 | 負責 |
|---|---|
| `kit.js` | 保存打包檔交出的 THREE 類別、`PALETTE`、seeded RNG、共用幾何工具 |
| `terrain.js` | 分塊高度場（128 m 一塊）與 LOD；草地、乾草、岩石、沙灘混合 shader |
| `water.js` | 海面：多層程式波紋法線、菲涅耳、太陽高光、岸邊浪花 |
| `roads.js` | 沿 `path` 鋪路面、路緣、人行道、標線；任意角度的路口斑馬線與停止線；護欄 |
| `buildings.js` | 第 5.3 節的建築風格與節慶設施 |
| `vegetation.js` | 第 5.4 節的植被，instancing，遠處低面數卡片 |
| `vehicles.js` | 主角車 3 款、交通車 7 款 |
| `people.js` | 模擬行人與裝飾人群 |
| `props.js` | 路燈、路牌、遮陽傘、船、浮標、旗幟、號誌燈殼 |
| `atmosphere.js` | 天空 shader、太陽、霧、陰影、tone mapping |
| `index.js` | 入口：接 hook、組裝場景、每幀更新、分塊顯示與隱藏 |

`index.js` 以 `<script type="module">` 放在打包檔的 module script 之前，確保 hook 在 `build()` 前就位。`world.type !== "coast"` 時所有 hook 不做事，舊地圖仍由 `semif-scenery.js` 負責，該檔不改。

### 4.3 打包檔補丁

沿用現有規則：每處都是只出現一次的精確字串替換，記錄在 `BUNDLE_PATCHES.md`，由 `tests/test_scenery.py` 的 `PATCHES` 鎖住。主執行緒（main）與 worker（wk）各自打。

| 類別 | 補丁 | 位置 |
|---|---|---|
| 生成 | 主題表加 `coast`（`limit:28,laneOffset:9}}` 之後） | main、wk |
| 生成 | `pt`／`y` 遇到 `coast` 交給 `SEMIF_WORLDGEN.generate` | main、wk |
| 生成 | worker 檔頭 import `semif-worldgen.js` | wk |
| 路線 | `ht`：`coast` 也走 `ut` | main、wk |
| 路線 | `ut`：相鄰兩個 id 相同時跳過（修「下一個目的地」的 `No drivable connection`） | main、wk |
| 路線 | `laneHalfWidth` 先讀 edge 自己的值 | main、wk |
| 路線 | 道路多邊形：帶 `path` 的 edge 不再以直線 `It(` 生成 | main、wk |
| 導航 | 導航文字表補上新路段類型 `harbour`、`coastal`、`valley`、`pass`（高速沿用既有的 `onramp`／`merge`／`interstate`／`exit`／`offramp`） | main、wk |
| 模擬 | 行人生成：`coast` 時改用 `visual` 的人行道路徑 | main、wk |
| 模擬 | `coast` 不產生路邊停車的交通車 | main、wk |
| 模擬 | 號誌路口轉彎限速在 `coast` 照常生效（打包檔在有路段資訊時會關掉它） | main、wk |
| 模擬 | 自由駕駛抵達後依固定的目的地鏈前往下一站 | main |
| 模擬 | worker 訊息帶 `SEMIF_MAP`，worker 用它重建世界（同時修正 7×7 自由駕駛時 worker 用 5×5 規劃的既有 bug） | main、wk |
| 畫面 | `coast` 時跳過打包檔的路面、路口墊、地面、glb 植被與路燈 | main |
| 畫面 | `th()`：`coast` 時不下載 `daylight.hdr` | main |
| 畫面 | 相機遠裁面 1200 → 2600 m | main |
| 畫面 | 主角車 `Jm`、交通車 `ch`、行人 `lh` 先問 `SEMIF_WORLD_KIT` 要網格 | main |
| 選單 | 預設世界：自由駕駛 `coast`，`lap=1` 維持 `city` | main |
| 選單 | 「Change map」改為「出發地點」 | main |

`index.html` 的 `SEMIF_MAP` 形狀不變（`test_benchmark_laps_keep_the_published_map_size` 鎖住它）；預設世界另用 `SEMIF_DEFAULT_WORLD`。

### 4.4 每幀更新

主角車、交通車、行人的網格由我們的工廠產生，位置、轉向、輪轉與四肢動畫仍由打包檔更新。號誌燈色沿用打包檔的邏輯（vision 讀的就是它），只換燈殼與燈桿造型。`index.js` 每幀只做：海浪時間、分塊顯示與隱藏、陰影相機跟隨、旗幟與摩天輪動畫。

## 5. 物件

### 5.1 車輛（`vehicles.js`）

- 車身以「側面輪廓曲線 × 各截面寬高」放樣成平滑曲面；零件分開：烤漆（`MeshPhysicalMaterial` clearcoat）、玻璃（材質名 `Glass`，引擎蓋視角時隱藏）、輪胎＋多輻輪框＋煞車碟、車燈、保險桿。
- 主角車 3 款，用現有相機切換器選擇：GT 跑車、60 年代敞篷跑車、拉力越野。
- 交通車 7 款：掀背、轎車、旅行車、SUV、廂型貨車、皮卡、速克達／機車。
- 對打包檔的承諾：主角車外框 4.75 × 1.9 m，交通車 4.2 × 1.9 m，機車 0.8 × 2.3 m；輪子節點 `wheel_fl/fr/rl/rr`，帶 `userData.radius`、`userData.front`，`children[0]` 為輪轂；`userData.wheelbase/eyeHeight/eyeForward`；每台車各自一份幾何（撞車凹陷會原地改寫幾何）。
- 車色：白、銀、香檳、青綠、海軍藍、酒紅、橄欖綠、沙色；尾燈用暗酒紅。

### 5.2 人物（`people.js`）

- 頭、軀幹、骨盆、上下臂、雙腿分段建模，肩與髖設樞紐，回傳 `userData.limbs = {legs:[2], arms:[2]}`。
- 變化：體型、膚色、髮型（短髮、長髮、包頭、草帽、棒球帽）、服裝（襯衫、洋裝、短褲）、配件（包包、墨鏡）。
- **模擬行人**一定穿深色下身，保住 `pedestrian` 遮罩依賴的深色剪影。這是色盤裡唯一允許落進該遮罩的顏色，以 `PALETTE.people.silhouette` 明列，測試只對它豁免 `pedestrian` 遮罩。
- **裝飾人群**（節慶觀眾、咖啡座、海灘）不在模擬裡，instancing；禁止使用剪影色，離車道中心線至少 8 m。

### 5.3 建築（`buildings.js`）

白牆別墅（陶土色瓦片，調成偏粉灰避開施工橘）、粉彩鎮屋（3–4 層、陽台、鼠尾草綠百葉窗、花台）、港口倉庫（拱門、石牆）、濱海咖啡館（遮陽棚、戶外座）、山丘農舍、燈塔、帶鐘樓的小教堂；節慶據點有主舞台、帳篷群、旗門拱道、摩天輪、展示車台。立面用 canvas 貼圖，同風格合併繪製。

### 5.4 植被與小物件

植被：棕櫚、義大利絲柏、橄欖、傘松、葡萄園行列、九重葛、夾竹桃、乾草叢。小物件：鑄鐵路燈、護欄、石牆、遮陽傘、港內漁船與遊艇（隨浪起伏）、浮標、海灘傘、節慶旗幟與橫幅、路標、里程石。

## 6. 氛圍（`atmosphere.js`、`water.js`）

- **時段：** 固定在午後偏晚（太陽仰角約 30°、偏暖），有長影但不至於讓陰影落進深色遮罩。半球光補冷色，陰影最暗處不低於直射亮度的 55%（與色塊測試的 ×0.55 一致）。
- **天空：** 程式化大氣散射漸層、柔和太陽光暈、高空薄雲；地平線附近偏淡藍灰，不落進 `emergency` 遮罩。
- **霧：** 距離霧，帶藍灰色的空氣透視，遠山與摩天輪呈層次。
- **海：** 青綠到藍綠（G 通道 ≥ 120），近岸較淺、有浪花；遠方與天空融合。
- **陰影：** 單一方向光陰影，鏡頭附近約 150 m，PCF 柔邊。
- **Tone mapping：** 改用 ACES Filmic。vision 擷取的是同一顆 renderer 的畫面，所以 tone mapping 同時影響 vision；色塊測試會把 ACES 曲線納入檢查（見 7.2）。
- **不加後製管線**（bloom、景深、動態模糊），以免 vision 畫面失真。速度感改由追車視角在高速時把 FOV 從 52° 平滑放大到約 62° 來做，只作用於追車視角，不影響車載相機與 vision。

## 7. 相容性與測試

### 7.1 舊地圖與官方分數

- `lap=1` 的預設世界維持 `city`、5×5，路線與分數不變；`?world=city|town|highway` 仍可用。
- `semif-scenery.js` 與舊 glb 不改。`world.type !== "coast"` 時新渲染器不做任何事。

### 7.2 測試

node harness 沿用 `tests/test_scenery.py` 的做法（以假的 kit 跑 JS，不需要瀏覽器與 GPU）。新增 `tests/test_worldgen.py` 與 `tests/test_world_render.py`：

- **補丁：** 新補丁加入 `PATCHES`，main 與 worker 各自鎖「原字串只出現一次、已替換」。
- **地圖：**
  - 決定性：同 seed 兩次輸出相同；多個 seed 都能生成。
  - 強連通、無死路；每條 edge 有 `path`，雙向 edge 有 `centerline` 與 `laneOffset`。
  - 道路之間除了在路口以外不相交（線段相交檢查）。
  - 每個路口的路臂恰好分成兩組相位；每個號誌與停車路口都有對應物件。
  - 限速下側向加速度 ≤ 3 m/s²。
  - 碰撞建築不壓到道路多邊形。
  - 每種路段 `kind` 都在導航文字表裡。
  - 從每個出發地點都能抵達每個目的地。
  - 裝飾人群離車道中心線 ≥ 8 m。
- **色彩：** `semif-world/` 內所有顏色字面值都在 `PALETTE`（含 shader 常數）；`PALETTE` 經 ×0.55–×1.65 亮度與 ACES 曲線後不落進任何相機遮罩；`people.silhouette` 只豁免 `pedestrian`。
- **工廠契約：** 主角車、交通車、行人工廠回傳的物件符合 5.1、5.2 的介面（輪子節點、尺寸、`limbs`、`Glass` 材質名、每次呼叫幾何獨立）。
- **舊地圖：** `world.type` 為 `city`／`town`／`highway` 時新渲染器的 hook 都回傳「不處理」。

### 7.3 實機驗證

- 用瀏覽器（Playwright）開 `/jevpilot/`：自由駕駛載入 coast、無主控台錯誤；開自駕從節慶據點跑完 2 中的目的地鏈；量測 fps；開啟 VISION 後抽樣幀檢查色塊。
- 截圖放 `docs/visual/solmare-coast/`，README 的「畫面與地圖」段落更新。
- 既有 Python 測試全部通過。

## 8. 實作分期

每期結束都能自由駕駛，且測試全綠。

1. **路網可開：** worldgen、生成與路線補丁、worker 同步、簡易道路與平地渲染；自駕在新路網上能跑完目的地鏈。
2. **地景：** 地形、海、天空、霧、陰影、tone mapping、完整道路與路口標線、護欄。
3. **聚落：** 建築、植被、小物件、節慶據點、摩天輪。
4. **車與人：** 主角車 3 款、交通車 7 款、模擬行人與裝飾人群、相機切換器接新主角車。
5. **收尾：** 效能調校、出發地點選單、速度感 FOV、截圖與文件。

## 9. 風險

- **打包檔補丁脆弱：** 沒有原始碼，靠精確字串替換；以測試鎖住，並在 `BUNDLE_PATCHES.md` 寫明理由。
- **worker 載入：** worker 是 module worker，檔頭 import 一個只碰 `globalThis` 的 IIFE；第 1 期先驗證。
- **大地圖效能：** 交通邏輯是 O(N²)，`/api/decide` 每次送出全部節點與道路；交通車數量以 fps 實測決定，必要時縮減送往決策端的導航資料（需另外確認不影響決策）。
- **vision 分布改變：** SigLIP 在新畫面上的表現與舊地圖不同；本案只保證色塊遮罩不誤報、自駕能跑完路線，不重新評估 SigLIP 準確度。
- **程式生成主角車的質感：** 以放樣曲面與 clearcoat 材質盡量拉高，第 4 期以截圖驗收。
