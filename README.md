# JevPilot-Vision

駕駛應用倉。世界、相機、JPEG、SigLIP、軌跡採樣、車道幾何與橫向控制屬於這裡。

裁決在 [SemArbiter](https://github.com/EndeavorYen/SemArbiter)。這一倉把這一幀的證據和選項 id 送過去，拿回依選項 id 對齊的 choice，或棄權。機率是讀出結果，不是另一套駕駛策略。

## 怎麼打 SemArbiter

`POST /v1/classifier`（或 `/v1/systemone`）：

- `state` 是這一步的證據。駕駛的 compact 視覺證據由應用寫入，不是像素。
- `questions.*.criteria` 是這一幀的選項 id。幾何慢行與停車軌跡留在應用的候選池，不由 SemArbiter 依號誌刪掉。
- 應用不把 JPEG 送到 SemArbiter。SemArbiter 不 import 這一倉。

## 程式還沒搬

駕駛程式仍在 SemArbiter 的 `jevpilot_vision/`。`python demo/server.py` 仍掛 `/jevpilot/` 與 `/v1/vision`。這一倉目前只有這份契約與 `LICENSE`。搬檔、搬 commit、改 remote 不在 SemArbiter #147。

官方駕駛分數仍是閉環乾淨完成。搬倉不改寫已發布數字。權重、快取與第三方原始紀錄不進這一倉。
