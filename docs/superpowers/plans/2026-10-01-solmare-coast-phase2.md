# Solmare Coast 第 2 期：地景與光影 Implementation Plan

> 執行方式：使用者要求「每期開 PR、一路做完」，本期不另等核准；計畫只列 task、介面與驗收，程式碼在實作時以 TDD 寫出（可在 node 測的邏輯先寫測試；shader 與畫面以截圖與 vision 煙霧測試驗收）。

**Goal:** 讓 Solmare Coast 好看：日照循環（晨→午→黃昏）、大氣天空與雲、會變色的太陽與長影、起伏的地形與海岸斷崖、有浪與反光的海、有質感的路面與護欄，主畫面加 bloom／調色／暗角。vision 的車載相機不受後製影響，色塊遮罩在任何時段都不誤報。

**Spec:** `docs/superpowers/specs/2026-10-01-solmare-coast-design.md` §6（氛圍）、§8 第 2 項。使用者在 2026-10-01 調整：主畫面可以加後製、可以加入 CC0 貼圖（約 10 MB 內）、光影要有日照循環（不做夜晚）。

## Global Constraints

- 只影響 `world.type === "coast"`；舊地圖與 `lap=1` 的畫面與行為不變。
- 打包檔補丁照舊：精確字串、只出現一次、列入 `COAST_PATCHES` 與 `BUNDLE_PATCHES.md`。
- vision 的車載相機畫面（`semif-layer.js` 自己的 render target）不經過後製。
- 每個時段下，`PALETTE`、天空與海的顏色乘上該時段的光色與 ×0.55–×1.65 亮度，都不落進相機色塊遮罩；暗部亮度不低於正午的 0.55 倍。
- 道路仍在 y=0；地形只在路肩外起伏。
- 新貼圖只用 Poly Haven CC0，記在 `textures/LICENSE.md`。

## Tasks

1. **Kit 與掛勾**：`kit()` 多交出 `ShaderMaterial, WebGLRenderTarget, OrthographicCamera, Vector2, Vector4, Matrix4, Quaternion, Euler, DataTexture, DepthTexture, TextureLoader, Fog, HemisphereLight, InstancedBufferAttribute`；新增 `sun(view, player)`（接管太陽位置）與 `present(view)`（接管主畫面輸出）兩個掛勾；`index.js` 在新地圖上每幀呼叫 `frame(view, dt)`。測試：補丁鎖、hook 在舊地圖回傳 falsy。
2. **日照模型 `daylight.js`**（純函式）：時鐘（預設 16:30 起、15 分鐘走完 06:00→19:30、`?time=HH:MM` 固定、`?daycycle=0` 暫停、`T` 鍵切換時段）、太陽方位與仰角、太陽色與強度、半球光、天空頂部與地平線色、霧色、曝光。測試：太陽東升南中西落、各時段色塊遮罩、暗部下限。
3. **天空與光照套用 `sky.js`**：天空穹頂 shader（大氣漸層、太陽盤與光暈、流動的雲）、每幀套用太陽方向／顏色、半球光、霧、曝光、加大陰影範圍以容納長影；HUD 顯示時間。
4. **地形 `terrain.js` 重寫**：距道路的距離場、分區起伏（北側山 160 m、山谷兩側、港口與節慶區平緩、山口外側斷崖）、海岸下降、坡度／高度決定草地、乾草、岩石、沙的混合；CC0 貼圖；分塊網格。測試：路面帶內高度為 0、海岸處低於海面、決定性。
5. **海 `water.js` 重寫**：依深度變色、多層波紋法線、菲涅耳反射天空色、太陽高光、岸邊浪花。
6. **道路升級 `roads.js`**：路面貼圖（world UV）、有立面的路緣、斷崖與山口外側的護欄。
7. **主畫面後製 `post.js`**：HDR render target、bloom、調色（依時段的暖冷）、暗角；`present()` 只作用在主畫面。
8. **驗收**：四個時段截圖、vision 煙霧測試（車載前鏡頭抽幀，`blobs_from_frame` 不出現號誌／施工／警示燈色塊）、fps 量測、自駕短程、文件、PR。
