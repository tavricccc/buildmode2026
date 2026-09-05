# 02 · Event Pipeline

## 1. 事件先於 Agent

Raw sensor data 不直接觸發 LLM。事件先經過 Normalizer 與 Correlator，合併成固定時間窗口，再由 Context Sentinel 判斷是否值得推論、詢問、記憶或保持安靜。

```text
raw camera/audio/IoT
  → normalized candidate
  → correlation / cooldown / quality
  → situation window
  → L0 change gate（只輸出有／無）
  → L1 multimodal observation（只在有變化時）
  → Main Agent judgment（可並行、bounded）
  → Known / Unknown / Hypothesis
  → attention policy
  → action or silent
```

## 2. Event contract

```json
{
  "event_id": "evt_...",
  "subject_id": "resident_demo",
  "event_type": "fall",
  "status": "candidate",
  "occurred_at": "2026-09-04T17:32:00+08:00",
  "source": "browser_vllm",
  "confidence": 0.78,
  "evidence_ids": ["evd_..."],
  "attributes": {},
  "dedup_key": "...",
  "schema_version": "event.v1",
  "config_version": "config.v1"
}
```

`fall`、`hydration` 是既有 canonical events。VLM 可以輸出 `event_candidates`，但只有非既有事件才進 `recognition_events`，例如 `door_knock`、`washing_machine`、`person_entered`、`object_phone`。candidate 必須有 domain、label、confidence、frame indexes、state、uncertainty；confidence < 0.55 只留在 observation uncertainty。

## 3. 目前兩階段 media window

- 每秒抽 2 張影像，每 5 秒形成一個有序窗口。
- L0 change gate 對窗口內相鄰低解析影像計算 temporal pixel delta，取變化峰值，並比較音訊能量相對上一窗口的變化，輸出單一 `changed=true/false`、`change_score`、門檻與簡短 gate 說明；一般影像變化須至少 2 個相鄰 pair 一致超過門檻，單一 pair 只有在達到強變化倍數時才通過。預設影像門檻為 `0.06`、音訊能量差門檻為 `0.06`。無變化時不呼叫 Omni，也不附送音訊。這可捕捉短暫經過後又離開畫面的變化，也不會讓畫面靜止時的語音／聲音輸入永遠被跳過。
- L0 判定有變化後，才把原窗口的 10 張 frame 與 5 秒 16 kHz mono audio 送給 L1 Nemotron observation。
- L1 的 `change_summary` 必須用一句繁體中文寫出觀察到的語意變化，例如姿態、人物、物件、聲音或場景的變化；不能只寫「有變化」。
- 5 FPS `visual_description` 是 action-only：只描述人物或物品動作／狀態變化；不得重複 scene bootstrap 的地點、牆面、地板、燈光、固定擺設或空間用途。沒有動作時明確輸出「這段窗口未觀察到人物或物品動作。」。
- 每個 L0 gate 窗口都保存 start/end offset，因此無變化的影片段也有完整時間軸；L1、detail、focus 與事件沿用同一串流 offset。
- camera session 前 5 秒先建立 scene context（地點、非人物物體與環境特徵），之後作為每一層 prompt 的 scene footnote。
- 一次 L1 observation request 送 Nemotron；完成後保存 window start/end offset、frame count、audio availability、change/warning signal、change_summary、latency 與 model/prompt version。
- Change gate 除了採用 Omni 的 `change_detected`，也會 deterministic 檢查 person appeared/left、new memorable audio/candidate、fall/hydration state 與新 persisted event；事件 signature 已出現時不重複觸發。
- 5 FPS worker 只預熱收集 frames，不對每個窗口呼叫模型；只有 `change_detected=true` 或 `warning_signal != none` 才開 detail inference：5 FPS、2 秒、10 frames + 2 秒 audio、1 秒 sliding stride。
- Main Agent 通常只讀 typed observation、5 FPS visual descriptions、scene context、事件與記憶摘要，不讀原始影片。
- 若 Main Agent 設定 `needs_further_attention=true`，再開 focus inference：2 FPS、10 秒、20 frames + 10 秒 audio，對照 detail descriptions、其他輸入與紀錄。
- 無警告時 Main Agent 可產生 `segment_record`，保存「某時間段觀察到的行動／未觀察到的行動／不確定性」。
- 預設 5 秒 non-overlap；若要更早回應，可將 stride 設為 1 秒，但必須調整 concurrency 與 queue backpressure。

Browser WebM 以 rolling segments 暫存最近 60 秒；raw media 不送給一般 Main Agent，並依 retention policy 受控清理。Nemotron 的 `chat_template_kwargs.enable_thinking` 是 per-request 設定；L0 不使用 reasoning，L1／Agent 目前預設仍關閉，之後可獨立開啟做品質實驗。

## 4. Existing-first mapping

| VLM observation | 優先結果 |
|---|---|
| down + near_floor + cross-frame lying | 交給既有 fall state machine |
| container near mouth + drinking motion | 交給既有 hydration state machine |
| audio door knock | `recognition_events` exception |
| person sitting/walking/entered | `recognition_events` exception |
| cup/phone/remote/pet/smoke | `recognition_events` exception |
| model 無法看清、位置不明、audio 不可用 | Known/Unknown，不建立確定事件 |

## 5. 去重與狀態

同一 input window 用 `stream_id + window_id + model input hash` 去重；同一種例外事件依 event-specific cooldown 聚合。`fall` 與 `hydration` 不可從 `event_candidates` 直接寫入計數，必須由既有 state machine 確認。任何重送不得增加 hydration session 或重複 intervention。

### 5.1 姿態轉換時間軸

`sitting`、`standing`、`lying` 是窗口觀察，不是事件。每個 live stream 另有一個 `posture_tracker:{stream_id}`，只在連續兩個有序窗口確認新姿態後產生 transition recognition event：

| 狀態轉換 | 事件 |
|---|---|
| `sitting → standing` | `person_stood_up` |
| `standing → sitting` | `person_sat_down` |
| `sitting/standing → lying` | `person_lay_down` |
| `lying → sitting/standing` | `person_got_up` |

每個轉換保存 `occurred_offset_ms`（上一個穩定觀察與第一次新姿態觀察的中點）、`first_observed_offset_ms`、`confirmed_offset_ms`、`from_state`、`to_state`、`confirmation_observations`、`evidence_frame_indexes` 與 `source_window_start/end`。Live stream 會把 offset 映射為絕對 ISO 8601 時間；缺人、遮擋或未知姿態不會被推論成坐下或起身。

並行 VLM 回應可能以非時間順序完成；tracker 會拒絕較舊 offset 回寫狀態，避免姿態倒退與重複事件。前端事件時間軸只顯示已確認 transition，瞬時 VLM observation 留在證據區。

## 6. Active Inquiry 入口

若 event correlation 得到「可能發生但物件／語意不清」的 situation，Context Sentinel 產生：

```json
{
  "information_gap": "items_added_to_fridge",
  "hypothesis": "resident may have stored groceries",
  "value_of_asking": 0.5,
  "urgency": "low",
  "suitable_interaction": true,
  "next_action": "ask_when_interruptible"
}
```

資訊不足且價值低時，輸出 `SILENT`；不可為了讓畫面有答案而補寫物品名稱或目前位置。

## 7. 驗收

- sensor event 先 correlation，再決定是否呼叫 VLM。
- 2 FPS/5 秒窗口有 10 個 offsets，缺 frame/audio 顯式標記。
- 既有事件不被例外候選取代。
- 重送與跨窗口 cooldown 不產生重複事件。
- WebSocket commit 後才發送，前端重連可 REST 恢復。
- 可用標註窗口驗收 `person_stood_up`／`person_sat_down` 的事件 F1、時間誤差中位數、重複事件率與錯誤提醒率。
