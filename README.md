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
