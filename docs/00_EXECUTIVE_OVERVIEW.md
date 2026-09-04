# 00 · 執行摘要

## 一句話定義

~~AI 長照 Agent OS 是一個以 Frigate 事件候選與多模態理解為主軸的照護輔助系統。~~

AI 長照 Agent OS 是一個本地優先、事件驅動、可審計的照護輔助系統：有限感知來源先建立事件與資料品質，Context / World State Agent 判斷已知、未知與異常；Resident Interaction Agent 在必要時低侵入詢問；Caregiver Agent 從隱私過濾後的資料產生日誌、趨勢與值得注意事項。

## 設計結論

系統不採用「事件發生後交給一個萬能 Agent」的模式，而採用以下閉環：

```text
感知 → 事件候選 → 多模態理解 → Event Ledger
     → 風險評估 → 政策閘門 → 介入 → 結果回寫
     → 長期觀察 → baseline / hypothesis → watchlist 更新
```

這個拆分讓計算成本、模型責任、醫療脈絡與安全行動彼此可控，也能在模型失效時退回規則、人工確認或僅記錄。

## 範圍

本設計涵蓋：

- Frigate NVR 事件 trigger 與影片/音訊證據索引。
- ASR／人聲理解、Video VLM、Audio Event Classification 的平行分流與匯合。
- Multimodal Event Bundle、Event Understanding、Risk、Intervention。
- Care Context / Watchlist Agent 與病史、FHIR、HealthKit、穿戴式、照護者設定的整合。
- Long-term Observer Agent 的閒置／夜間 baseline、trend、frequency、sequence、pattern 分析。
- Raw Evidence、Sensor Event、Observation、Interpretation、Risk Assessment、Intervention、Hypothesis、Baseline、Watchlist、Medical Context 的資料分層。
- T0–T3 動態模型路由、GPU/CPU 排程、版本與成本審計。
- L0–L4 介入狀態機與 L4 deterministic safety gate。

## 不在範圍內的承諾

本系統不是診斷工具，也不是在沒有場域政策、預先授權與確認閘門的情況下自動呼叫緊急服務的系統。模型推論可以產生建議、證據摘要與不確定性，但不能自行把假設升格為病史事實，也不能修改緊急行為門檻。

## 核心架構

產品主路徑是：`有限感知 → Event Ledger → World State → 必要時詢問 → 記憶／提醒 → 隱私聚合 → 照護者摘要`。Frigate、ASR、VLM 與健康來源都是 adapter；Risk、Policy、Scheduler 與 Audit 是確定性治理骨幹。

資料與控制流如下：

1. Frigate NVR 從攝影機、麥克風與整合裝置產生低成本事件候選。
2. Router 將候選分流給 ASR／人聲理解、Video VLM 與 Audio Event Classifier。
3. Assembler 依事件 ID、時間窗、裝置與 subject 匯合成 Multimodal Event Bundle。
4. Event Understanding Agent 產生 Observation 與 Interpretation，寫入 Event Ledger。
5. Risk Agent 評估風險與不確定性，Policy Gateway 再決定允許的介入範圍。
6. Intervention Agent 執行 L0–L4，並將回應、超時、取消與接手結果回寫。
7. Long-term Observer Agent 讀取 Ledger、健康脈絡與基線；Memory/Consolidation Agent 保存結果，Watchlist Agent 產生可審核的觀察策略。

## 最重要的安全決策

1. Risk Agent 與 Intervention Agent 分離；Risk 不可直接通知或求助。
2. Watchlist 是觀察策略，不是緊急政策；Agent-suggested watch item 預設只能進入待審核狀態。
3. L4 必須同時滿足 deterministic policy、明確預先授權、證據品質、確認／超時條件與完整審計。
4. 每一筆模型輸出都保留 source、timestamp、model/policy version、confidence、provenance 與 data quality。
5. 事件與外部健康資料採最小必要 context，避免把完整病史或全部影音暴露給每個模型。

## 導入順序

先用單一場域、少量事件類型做可觀測的 L0–L2 Demo，再加入 L3 照護者確認流程，最後才在經過場域政策與安全驗證後評估 L4。實作里程碑詳見 [10_MVP_AND_ROADMAP.md](10_MVP_AND_ROADMAP.md)。
