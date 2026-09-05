# 10 · Long-term Observer

Observer 沿用 v3：每日彙總 hydration、fall、health 與 coverage，比較 7/30 日 baseline，保存可反查 finding，不做診斷或直接通知。

達到前端設定的變化門檻時，呼叫 active `analysis` model slot；本地與雲端 endpoint 契約相同，只傳 fixed-size daily summaries 和 baseline comparison，不傳整段影片。

前端可設定 schedule/timezone、short/baseline windows、minimum coverage、change thresholds、model slot、timeout、是否自動執行；修改建立 config version。同日/config version 重跑不可重複產生 finding。

後台可手動重跑、acknowledge/dismiss，並查看 endpoint/model、input summary、supporting dates、coverage、confidence 與 config version。
