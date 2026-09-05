#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini REST API 影片理解測試腳本
使用原生 REST API 調用 gemini-3.5-flash-lite 分析影片內容。

支援兩種模式：
1. inline_data: 透過 Base64 將影片直接夾帶在 REST 請求中（適合 < 20MB 小型影片，速度最快）
2. files_api: 透過 Google File Upload REST API（支援可續傳上傳與處理狀態輪詢，適合大影片）
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 強制終端輸出 UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def load_api_key(env_path: Path) -> str:
    """從環境變數或 .env 檔案讀取 API 金鑰"""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY")
    if api_key:
        return api_key

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key in ("API_KEY", "GEMINI_API_KEY"):
                    return val

    raise ValueError(
        f"找不到 API Key！請在 {env_path} 填寫 API_KEY=xxx 或設定環境變數 GEMINI_API_KEY。"
    )


def call_with_inline_data(
    api_key: str,
    video_path: Path,
    prompt: str,
    model: str = "gemini-3.5-flash-lite",
    mime_type: str = "video/mp4",
) -> str:
    """
    方法 1: inline_data (Base64)
    直接將影片以 Base64 編碼放進 REST API 的 contents.parts 中發送。
    REST 端點: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
    """
    print(f"[*] 讀取影片檔案: {video_path.name} ({video_path.stat().st_size / (1024 * 1024):.2f} MB)")
    print("[*] 正在進行 Base64 編碼...")
    video_bytes = video_path.read_bytes()
    b64_str = base64.b64encode(video_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_str,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ]
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"[*] 發送 REST 請求至模型 {model} (inline_data)...")
    start_t = time.time()
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - start_t
    print(f"[*] API 響應完成，耗時: {elapsed:.2f} 秒")

    try:
        return res["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as err:
        return f"解析回應格式失敗: {err}\n完整回應: {json.dumps(res, indent=2, ensure_ascii=False)}"


def call_with_file_api(
    api_key: str,
    video_path: Path,
    prompt: str,
    model: str = "gemini-3.5-flash-lite",
    mime_type: str = "video/mp4",
) -> str:
    """
    方法 2: Google Files API (Resumable Upload)
    1. POST upload/v1beta/files 初始化上傳獲取 upload URL
    2. POST 上傳影片二進位資料
    3. 輪詢檔案狀態直到 ACTIVE
    4. 呼叫 models/{model}:generateContent 傳入 file_data
    """
    file_size = video_path.stat().st_size
    print(f"[*] 讀取影片檔案: {video_path.name} ({file_size / (1024 * 1024):.2f} MB)")

    # 步驟 1: 初始化可續傳上傳 (Resumable Upload)
    print("[*] 步驟 1/4: 向 File API 初始化上傳工作...")
    init_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
    init_metadata = json.dumps({"file": {"display_name": video_path.name}}).encode("utf-8")
    init_headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }
    req_init = urllib.request.Request(init_url, data=init_metadata, headers=init_headers, method="POST")
    with urllib.request.urlopen(req_init) as resp:
        upload_url = resp.headers.get("x-goog-upload-url")

    if not upload_url:
        raise RuntimeError("未能取得 x-goog-upload-url，請檢查 API 金鑰或網路。")

    # 步驟 2: 上傳檔案資料
    print("[*] 步驟 2/4: 正在上傳影片資料到 Google Files API...")
    data = video_path.read_bytes()
    upload_headers = {
        "Content-Length": str(file_size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    }
    req_upload = urllib.request.Request(upload_url, data=data, headers=upload_headers, method="POST")
    with urllib.request.urlopen(req_upload) as resp:
        upload_result = json.loads(resp.read().decode("utf-8"))

    file_info = upload_result.get("file", {})
    file_name = file_info.get("name")
    file_uri = file_info.get("uri")
    print(f"[*] 上傳成功: {file_name} (URI: {file_uri})")

    # 步驟 3: 輪詢檔案處理狀態
    print("[*] 步驟 3/4: 等待影片後端轉碼處理 (等待 state 為 ACTIVE)...")
    state = file_info.get("state")
    while state == "PROCESSING":
        time.sleep(2)
        poll_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
        with urllib.request.urlopen(poll_url) as poll_resp:
            poll_info = json.loads(poll_resp.read().decode("utf-8"))
            state = poll_info.get("state")
            print(f"    - 當前狀態: {state}")

    if state != "ACTIVE":
        raise RuntimeError(f"檔案處理失敗，當前狀態: {state}")

    # 步驟 4: 呼叫 generateContent
    print(f"[*] 步驟 4/4: 呼叫模型 {model}:generateContent 分析影片...")
    gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "file_data": {
                            "mime_type": mime_type,
                            "file_uri": file_uri,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ]
    }
    req_gen = urllib.request.Request(
        gen_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start_t = time.time()
    with urllib.request.urlopen(req_gen) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - start_t
    print(f"[*] 模型推理完成，耗時: {elapsed:.2f} 秒")

    try:
        return res["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as err:
        return f"解析回應格式失敗: {err}\n完整回應: {json.dumps(res, indent=2, ensure_ascii=False)}"


def main():
    parser = argparse.ArgumentParser(description="使用 Gemini REST API 呼叫 gemini-3.5-flash-lite 分析影片")
    parser.add_argument(
        "--video",
        type=str,
        default=None,
        help="影片路徑（預設自動尋找當前目錄或上一層的 YouTube Shorts mp4 檔案）",
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["inline", "files_api"],
        default="inline",
        help="傳輸模式: inline (Base64直接送，適合<20MB影片) 或 files_api (Google檔案上傳API)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.5-flash-lite",
        help="Gemini 模型名稱 (預設: gemini-3.5-flash-lite)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="請詳細分析並解讀這部影片的完整內容：\n1. 影片發生的場景與主要動作\n2. 每個階段出現的物體（如瓶子形狀、液體顏色）以及它們滾下階梯後的結果\n3. 影片是否有聲音/音效特色\n4. 總結這部影片的主題與風格\n請以繁體中文結構化回答。",
        help="給模型的提問 Prompt",
    )

    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    env_file = script_dir / ".env"

    api_key = load_api_key(env_file)

    # 尋找目標影片
    video_path = None
    if args.video:
        video_path = Path(args.video)
        if not video_path.is_absolute():
            video_path = (Path.cwd() / video_path).resolve()
    else:
        # 自動搜尋
        candidates = list(project_root.glob("*.mp4")) + list(script_dir.glob("*.mp4"))
        if candidates:
            video_path = candidates[0]

    if not video_path or not video_path.exists():
        print("錯誤: 找不到影片檔案！請使用 --video 指定影片路徑。")
        sys.exit(1)

    print("=" * 60)
    print(f"模型: {args.model}")
    print(f"方法: {args.method}")
    print(f"影片: {video_path}")
    print("=" * 60)

    try:
        if args.method == "inline":
            result = call_with_inline_data(api_key, video_path, args.prompt, model=args.model)
        else:
            result = call_with_file_api(api_key, video_path, args.prompt, model=args.model)

        print("\n" + "=" * 25 + " 模型解析結果 " + "=" * 25)
        print(result)
        print("=" * 64)

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"\n[HTTP Error {e.code}]: {e.reason}")
        print(f"回應內容:\n{err_body}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[執行錯誤]: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
