# 打包檔修補清單

`assets/main-CvLEeHjW.js` 是打包好的產物，這一倉和 SemArbiter 都沒有它的原始碼。下面是對它做的全部修補。每一處都是原字串只出現一次的精確替換，`tests/test_scenery.py::test_bundle_patches_are_applied_once` 會鎖住它們。

| 名稱 | 原文 | 改為 | 為什麼 |
|---|---|---|---|
| `map-size-city` | `size:5,traffic:28,buildings:.97,limit:18` | `size:window.SEMIF_MAP?.size??7,traffic:window.SEMIF_MAP?.cityTraffic??40,…` | Skyline City 的尺寸由 `index.html` 決定：自由駕駛 7×7 個路口（約 ±485 m），`lap=1` 維持 5×5（約 ±330 m，已發布分數的地圖），`?size=` 可覆寫；交通車依尺寸增減 (#11) |
| `map-size-town` | `size:5,traffic:14,buildings:.62,limit:14` | `size:window.SEMIF_MAP?.size??7,traffic:window.SEMIF_MAP?.townTraffic??22,…` | Small town 同上（7×7 約 ±440 m） |
| `scenery-kit` | `build(){this.scenery&&(this.scenery.active=!1)` | `build(){window.SEMIF_SCENERY?.kit?.({…});…` | 把打包檔內的 three.js 類別與材質輔助函式交給 `semif-scenery.js` |
| `scenery-object` | `for(let e of n.objects){if(e.type===\`hill\`)` | `…{if(window.SEMIF_SCENERY?.object?.(r,e,this))continue;if(e.type===\`hill\`)` | 場景層可以接手單一物件（目前是建築）的外觀 |
| `scenery-built` | `this.ready=Promise.all([t,d,this.scenery.ready])}` | `…,window.SEMIF_SCENERY?.built?.(this)}` | 場景建好後的處理：號誌燈罩、交通車、天空、重新合併批次 |
| `scenery-minimap` | `$.rotate(-n.heading),$.lineCap=\`round\`` | `$.rotate(-n.heading),window.SEMIF_SCENERY?.minimap?.($,e,i,r),$.lineCap=\`round\`` | 小地圖在道路下方畫建築與公園輪廓 |

每個 hook 都用 `?.` 呼叫。沒有載入 `semif-scenery.js`，或是網址帶 `?scenery=0` 時，除了地圖尺寸之外，打包檔的行為和修補前一樣；`lap=1` 或 `?size=5` 時，地圖尺寸也和修補前一樣。

修補只改外觀和地圖尺寸，不動物理、路網生成規則、號誌時序、交通規則或規劃器。自由駕駛的大地圖上，交通車、行人和路線都跟 5×5 時不同；`lap=1` 的官方跑圈仍是原本的地圖與路線。

## Solmare Coast（`coast` 地圖）

自由駕駛改開 `semif-worldgen.js` 生成的 Solmare Coast。打包檔裡有兩份模擬：頁面上的 `main-CvLEeHjW.js`（main），以及規劃器 worker `planner.worker-DFdG3q6n.js`（wk）。worker 拿到 seed 和地圖名稱後，會自己重建一次世界，所以兩份都要修補。原字串與替換字串的全文在 `tests/test_coast_patches.py::COAST_PATCHES`；該測試會鎖住每一處只出現一次，並在 node 裡用 worker 的模擬實際跑這張地圖。

| 名稱 | 檔案 | 改了什麼 | 為什麼 |
|---|---|---|---|
| `coast-generate`、`coast-generate-worker` | main、wk | `coast` 或 `coast:<出發地點>` 交給 `SEMIF_WORLDGEN.generate`，再用打包檔自己的 Dijkstra 和路線產生器排出第一條路線 | 新地圖的入口 |
| `coast-worker-import` | wk | 檔頭 `import"/jevpilot/semif-worldgen.js"` | worker 沒有 `window`，要自己載入生成器 |
| `coast-theme`、`coast-theme-worker` | main、wk | 主題表加入 `coast` | 交通車數量與最高速度；`?world=coast` 也要找得到 |
| `coast-route`、`coast-route-worker` | main、wk | `coast` 的路線沿每條路自己的 `path` 走 | 原本只有 Interstate 這樣做，棋盤圖會走直線 |
| `coast-same-node`、`coast-same-node-worker` | main、wk | 路線產生器跳過相鄰兩個相同的節點 | 自由駕駛的「下一站」路線會把終點節點重複一次，原本會丟例外 |
| `coast-lane-width`、`coast-lane-width-worker` | main、wk | 車道半寬先讀路段自己的 `laneHalfWidth` | SS-1 每條車道 4 m，其他路 6 m |
| `coast-road-polygons`、`coast-road-polygons-worker` | main、wk | 帶 `path` 的路段不再用兩端點的直線長方形當路面 | 彎路的路面改由 `connectorRoads` 提供 |
| `coast-navigation`、`coast-navigation-worker` | main、wk | 導航文字表加入新的路段種類 | 未知種類會讓每次導航都丟例外 |
| `coast-turn-distance`、`coast-turn-distance-worker` | main、wk | 新的路段種類以下一個路口算轉彎距離 | 原本只有 `local` 這樣算 |
| `coast-turn-caps`、`coast-turn-caps-worker` | main、wk | 路口轉彎的減速在 `coast` 照常生效 | 打包檔在路線帶路段資訊時會關掉它；港口的號誌路口需要它 |
| `coast-pedestrians`、`coast-pedestrians-worker` | main、wk | 行人由 `world.pedestrians()` 產生 | 原本的步道是兩節點間的直線，在彎路上會走到路外 |
| `coast-no-parked`、`coast-no-parked-worker` | main、wk | `coast` 不產生停在車道上的交通車 | 停車只右移 1.6 m，仍佔車道，後車不超車會永久排隊 |
| `coast-worker-message`、`coast-worker-map` | main、wk | 規劃請求附上地圖名稱（含出發地點）與 `SEMIF_MAP`，worker 先設好再建世界 | worker 才能建出和頁面相同的地圖 |
| `map-size-city-worker`、`map-size-town-worker` | wk | worker 的城市、小鎮尺寸改讀 `SEMIF_MAP`（getter） | 修正 #11 的問題：自由駕駛 7×7 時，worker 原本一直在 5×5 地圖上規劃。`lap=1` 本來就是 5×5，不受影響 |
| `coast-default-world`、`coast-world-fallback` | main | 沒指定 `world` 時，改用 `index.html` 設的 `SEMIF_DEFAULT_WORLD`；`coast:<出發地點>` 是合法的地圖名稱 | 自由駕駛預設開新地圖，`lap=1` 維持城市 |
| `coast-world-picker`、`coast-picker-value`、`coast-new-layout` | main | 新地圖上，選單改為「Start from」加 5 個出發地點；「New layout」保留出發地點 | 舊地圖不再列在新地圖的選單裡 |
| `coast-next-destination`、`coast-commit-destination` | main | 抵達後的下一站依固定的目的地鏈；路線排得出來才確認換站 | 原本是隨機挑一個節點；路線失敗時打包檔每個 tick 都會再問一次，先換站會一路跳站 |
| `coast-ground`、`coast-roads-off`、`coast-pads-off`、`coast-streetlights-off` | main | `coast` 不畫打包檔的地面、直線路面、路口方塊和 glb 路燈 | 這些都由 `semif-world/` 負責 |
| `coast-kit-classes` | main | `kit()` 多交出 ShaderMaterial、RenderTarget、正交相機、向量與矩陣、DataTexture、TextureLoader、Fog、HemisphereLight、InstancedBufferAttribute | 渲染器要自己寫天空、海、後製與 instancing；壓縮名稱由 `test_kit_classes_are_the_classes_they_claim_to_be` 核對 |
| `coast-sun` | main | 太陽位置先問 `SEMIF_SCENERY.sun(view, player)` | 日照循環：太陽方向依時間改變 |
| `coast-present` | main | 主畫面輸出先問 `SEMIF_SCENERY.present(view)` | 後製只作用在主畫面；車載相機另外渲染，不受影響 |
