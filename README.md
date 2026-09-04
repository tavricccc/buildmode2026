# AI 長照 Agent OS

本 repository 是「AI 長照 Agent OS」的架構設計與黑客松原型。最新 v3 方案直接以固定節拍 QwenVL loop 持續分析 RTSP／Replay 影像，不再由 Frigate 事件作前置篩選；舊版架構仍保留供比較。

~~上一版以有限感知來源 → Context/World State → Resident Interaction → Caregiver 三個產品 Agent 為主路徑。~~ 這個產品分層保留作設計參考；目前可執行 v3 的實作邊界以 `docs-implementation-v3/` 為準，並由 Event Understanding、Health Context、Risk、Intervention 等 logical agents 落地。

## 文件入口

最新完整實作文件位於 [docs-implementation-v3/README.md](docs-implementation-v3/README.md)，舞台簡化版位於 [demo-v2/README.md](demo-v2/README.md)。v2 文件保留於 `docs-implementation-v2/`，不覆寫。

完整 Markdown 開發文件請從 [docs/README.md](docs/README.md) 開始，建議依序閱讀：

1. [執行摘要](docs/00_EXECUTIVE_OVERVIEW.md)
2. [系統架構](docs/01_SYSTEM_ARCHITECTURE.md)
3. [事件管線](docs/02_EVENT_PIPELINE.md)
4. [Agent 架構](docs/03_AGENT_ARCHITECTURE.md)
5. [記憶體與資料模型](docs/04_MEMORY_AND_DATA_MODEL.md)
6. [風險與介入](docs/05_RISK_AND_INTERVENTION.md)
7. [長期觀察](docs/06_LONG_TERM_OBSERVER.md)
8. [模型路由與 Runtime](docs/07_MODEL_ROUTING_AND_RUNTIME.md)
9. [健康脈絡整合](docs/08_HEALTH_CONTEXT_INTEGRATION.md)
10. [部署與安全](docs/09_DEPLOYMENT_AND_SECURITY.md)
11. [MVP 與 Roadmap](docs/10_MVP_AND_ROADMAP.md)

最新完整實作文件：[docs-implementation-v3/README.md](docs-implementation-v3/README.md)；舞台簡化版：[demo-v2/README.md](demo-v2/README.md)。舊版目標架構與 Mermaid 仍保留於 `docs/12_TARGET_ARCHITECTURE.md` 與 `docs/diagrams/`，供比較與後續產品化使用。

現有的互動式原型位於 [care_agent_demo_frigate_vad_m3_sqlite.html](care_agent_demo_frigate_vad_m3_sqlite.html)；其中 Frigate／MiniMax 舊節點仍保留並以刪除線標示。

## 重要安全邊界

- Agent 產出的 Observation、Interpretation、Risk、Hypothesis 與 Fact 分層保存，保留來源、版本、時間與信心。
- Watchlist Agent 可以提出觀察候選，但不能直接建立或修改緊急規則。
- L4 Emergency Protocol 必須通過 deterministic policy、預先授權、條件確認與完整審計；單靠 LLM 不得啟動緊急服務。
- 本系統是照護輔助與事件治理架構，不宣稱診斷、治療或取代專業照護。
