# 02 · Event、Agent、Policy 與設定契約

事件信封與 v3 相容，但模型來源統一記錄 local/cloud endpoint：

```json
{
  "event_id": "evt_01J...",
  "event_type": "fall",
  "status": "candidate",
  "occurred_at": "2026-09-04T14:32:10+08:00",
  "confidence": 0.78,
  "evidence_ids": ["evd_01J..."],
  "model_endpoint_id": "vision_primary",
  "deployment_type": "local|cloud",
  "model_id": "configured-after-deploy",
  "prompt_version": "vision-events.v2",
  "schema_version": "event.v1",
  "config_version": "cfg_01J...",
  "dedup_key": "sha256:..."
}
```

Event Understanding、Health Context、Risk、Intervention logical agents 與 v3 權限不變。任何 Agent 都不能讀取 secret、任意 SQL、擴大收件人或繞過 Policy Gateway。

## Policy 設定

跌倒確認窗口、無恢復通知時間、最低信心、飲水容量／目標、分析窗口與 reminder 均為 `ui_editable`。這些值是產品設定而非醫療標準。

設定更新採 optimistic concurrency：PATCH 必須帶 `base_version`。backend 驗證成功後建立新版本；衝突回 `409 CONFIG_VERSION_CONFLICT`。每個 job 在開始時綁定 config version，途中更新不改寫既有 job。

高風險變更（降低 fall confidence、縮短 alert timer、變更通知 recipient）需二次確認並寫 audit event，但仍可在本機管理前端完成。
