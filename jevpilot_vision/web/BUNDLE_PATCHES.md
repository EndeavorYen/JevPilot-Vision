# 打包檔修補清單

`assets/main-CvLEeHjW.js` 是打包好的產物，這一倉和 SemArbiter 都沒有它的原始碼。下面是對它做的全部修補。每一處都是原字串只出現一次的精確替換，`tests/test_scenery.py::test_bundle_patches_are_applied_once` 會鎖住它們。

| 名稱 | 原文 | 改為 | 為什麼 |
|---|---|---|---|
| `map-size-city` | `size:5,traffic:28,buildings:.97,limit:18` | `size:7,traffic:40,buildings:.97,limit:18` | Skyline City 從 5×5 放大到 7×7 個路口（約 ±330 m → ±485 m），交通車依面積增加 (#11) |
| `map-size-town` | `size:5,traffic:14,buildings:.62,limit:14` | `size:7,traffic:22,buildings:.62,limit:14` | Small town 同上（約 ±300 m → ±440 m） |
| `scenery-kit` | `build(){this.scenery&&(this.scenery.active=!1)` | `build(){window.SEMIF_SCENERY?.kit?.({…});…` | 把打包檔內的 three.js 類別與材質輔助函式交給 `semif-scenery.js` |
| `scenery-object` | `for(let e of n.objects){if(e.type===\`hill\`)` | `…{if(window.SEMIF_SCENERY?.object?.(r,e,this))continue;if(e.type===\`hill\`)` | 場景層可以接手單一物件（目前是建築）的外觀 |
| `scenery-built` | `this.ready=Promise.all([t,d,this.scenery.ready])}` | `…,window.SEMIF_SCENERY?.built?.(this)}` | 場景建好後的處理：號誌燈罩、交通車、天空、重新合併批次 |
| `scenery-minimap` | `$.rotate(-n.heading),$.lineCap=\`round\`` | `$.rotate(-n.heading),window.SEMIF_SCENERY?.minimap?.($,e,i,r),$.lineCap=\`round\`` | 小地圖在道路下方畫建築與公園輪廓 |

每個 hook 都用 `?.` 呼叫。沒有載入 `semif-scenery.js`，或是網址帶 `?scenery=0` 時，除了地圖尺寸之外，打包檔的行為和修補前一樣。

修補只改外觀和地圖尺寸，不動物理、路網生成規則、號誌時序、交通規則或規劃器。地圖變大後，交通車與行人的路線、`lap=1` 的終點會跟著改變。
