# 03 · 跌倒與喝水視覺 Pipeline

## 1. Local VLM 輸出契約

一次推論接收 1–8 張依序排列的 frame，輸出：

```json
{
  "observed_at_offset_ms": 18340,
  "person_visible": true,
  "posture": "standing|sitting|lying|unknown",
  "vertical_transition": "up|down|none|unknown",
  "near_floor": false,
  "drink_container": "cup|bottle|other|none|unknown",
  "container_near_mouth": false,
  "drinking_motion": false,
  "confidence": 0.0,
  "supporting_frame_indexes": [0, 3, 7],
  "uncertainty_reasons": []
}
```

Pydantic 驗證失敗時保存 invalid model call，不得更新事件狀態。

## 2. 跌倒狀態機

```text
idle
  → suspect：快速向下／由站坐轉躺／人物接近地面
  → confirmed：窗口內多次 observation 支持倒地，達最低信心
  → recovering：人物重新坐起或站立
  → resolved：恢復狀態持續達設定時間

suspect → dismissed：後續畫面不支持，或只是正常坐／躺
confirmed → alert_due：超過 no_recovery_alert_sec 且沒有恢復證據
```

跌倒不可由單張 `lying=true` 直接確認；至少需要 transition 或跨 frame 的持續證據。沙發、床及地板需靠測試影片校正 prompt 與 negative cases。

`attributes` 至少保存：

```json
{
  "initial_posture": "standing",
  "final_posture": "lying",
  "near_floor": true,
  "confirmed_duration_ms": 9300,
  "recovered_at": null,
  "alert_due_at": "..."
}
```

## 3. 喝水狀態機

```text
idle
  → suspect：偵測到杯／瓶且靠近嘴部
  → confirmed：連續 frame 出現容器靠嘴與飲用動作
  → active：同一飲水 session 內的重複 observation
  → completed：容器離開嘴部並超過 session close window

suspect → dismissed：只有拿杯、倒水或容器遮擋，沒有飲用動作
```

只有 `completed` session 計入喝水次數。`dedup_key` 需包含 subject、source 與 session 時間桶，重播或模型重試不得增加次數。

## 4. 飲水量估算

MVP 不嘗試從任意容器精確辨識毫升數。每個 subject 設定 `estimated_ml_per_session`，預設 200 ml；資料庫同時保存：

- `session_count = 1`
- `estimated_ml`
- `estimation_method = configured_serving`
- `estimation_confidence`

未來可加入已校正透明容器的液面前後差，但不得覆寫原始估算方法。

## 5. 抽幀與觸發

- Replay 初始基線：1 FPS、8 秒 sliding window、每 2 秒最多一次 VLM job。
- 若已進入 `fall.suspect`，可暫時提高抽樣率；事件解除後恢復基線。
- Local VLM queue 只保留最新有用窗口；過期普通工作可丟棄，但高風險 suspect window 不可被普通工作取代。
- 每次 inference 保存 frame offsets，不必把每張 frame 永久存圖。

## 6. 最小測試影片

| 類型 | 正例 | 主要負例 |
|---|---|---|
| 跌倒 | 站立後倒地並維持不動 | 坐沙發、躺沙發、彎腰撿物、坐地板 |
| 喝水 | 杯／瓶靠嘴並飲用 | 拿杯走動、倒水、舉杯但未喝、手靠近臉 |

