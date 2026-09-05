# 00 · 執行摘要

## 一句話定義

**Ambient Care Agent OS 在有限感知下建立生活脈絡，並知道何時值得注意、何時資訊不足、何時應該詢問或保持安靜。**

它不是「看著老人」的 AI，也不是把所有 camera/audio 原始資料交給一個萬能 Agent。Camera、microphone、IoT、手機與 wearable 都是稀疏 sensors；核心價值在 Event Ledger、World State、Uncertainty、Memory 與治理後的 intervention。

## 核心問題

單一感測器通常只知道局部現象：人離開鏡頭不代表離開家、冰箱關閉不代表知道拿了什麼、沒有聲音不代表沒有事情發生。因此系統必須能保存 `UNKNOWN`，並將「資訊缺口」變成可評估的 Active Inquiry，而不是幻覺式補全。

## 三個邏輯 Agent

1. **Context Sentinel**：整理目前 Known、Unknown、Hypothesis、confidence 與值得注意的變化。
2. **Resident Interaction Agent**：以 Default Silent 為原則，在值得知道且可打擾時詢問、提醒或短暫對話。
3. **Caregiver Agent**：只讀 privacy-aggregated facts、trend 與 findings，產生可追溯的照護摘要。

三者共用同一個 Event/Memory 核心與 deterministic Policy；不拆成三個獨立模型服務。現階段三個 Agent 可共用本機 Nemotron vLLM，但 prompt、context、tools 與權限必須分開。

## 範圍

- 單一住戶、單一場域、local-first。
- Browser camera/microphone continuous MediaStream；目前以本機 Nemotron Omni vLLM 做 2 FPS、5 秒、10-frame + audio window。
- 既有 `fall`、`hydration` 事件優先沿用；家庭聲音、人物活動、非人物物件作為有證據的例外 `recognition_events`。
- Event correlation、World State、Event/Semantic/Scheduled Memory、Active Inquiry、privacy aggregation、health snapshot 與長期 baseline。
- Frigate、MQTT、IoT、wearable 為可插拔 adapters，不是 current VLM path 的必要條件。

## 不做的承諾

- 不做醫療診斷、治療建議或自動判定失能等級。
- 不在浴室、臥室部署鏡頭，不在對話窗外自動啟動逐字 ASR。
- 不把單張影像、單次聲音或模型自由文字直接變成確定事實。
- 不自動聯繫社工、政府或緊急服務；L4 executor 不在本版。
- 不把照護者預設暴露到 Level 3 raw video/audio/transcript。

## 成功判準

一次可重現的 Demo 應能展示：事件進入 → 脈絡整理 → Known/Unknown/Hypothesis → 需要時詢問 → 回答寫入 Memory → 依時間產生提醒 → 照護者只看到摘要與證據索引。每一步都能追溯來源、時間、信心、版本與政策。

## current implementation status

目前已完成 browser multimodal stream、Nemotron image/audio request、structured observation、fall/hydration state machine、exception event candidates、SQLite、WSS dashboard 與基本 Observer。下一個主要工作是 Context Sentinel/Active Inquiry、Policy/Intervention 與受限 Resident Interaction；Gate 2b 的 Silero/Whisper、完整 Agent tools 與 Gate 3 的 E2E 仍待完成。
