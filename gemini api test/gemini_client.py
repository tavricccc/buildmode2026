#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Multimodal REST API Client
支援影片 (Video)、音訊 (Audio)、圖片 (Image) 與純文字 (Text) 原生輸入的方便調用腳本。
純標準庫實現 (無需第三方套件依賴)，預設調用 gemini-3.5-flash-lite。
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

# 確保在 Windows / 各種終端輸出 UTF-8
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 常見多媒體副檔名 MIME-Type 對應表
CUSTOM_MIME_TYPES = {
    # 影片
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".3gp": "video/3gpp",
    ".flv": "video/x-flv",
    # 音訊
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".weba": "audio/webm",
    # 圖片
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    # 文件
    ".pdf": "application/pdf",
}

# 單一請求 inline_data 建議上限 (20 MB)
INLINE_MAX_BYTES = 20 * 1024 * 1024


def detect_mime_type(file_path: Union[str, Path]) -> str:
    """自動偵測檔案 MIME-Type"""
    ext = Path(file_path).suffix.lower()
    if ext in CUSTOM_MIME_TYPES:
        return CUSTOM_MIME_TYPES[ext]
    mime, _ = mimetypes.guess_type(str(file_path))
    return mime or "application/octet-stream"


def find_api_key(env_path: Optional[Path] = None) -> str:
    """自動尋找並載入 Gemini API Key"""
    # 1. 優先讀取環境變數
    for key in ("GEMINI_API_KEY", "API_KEY"):
        val = os.environ.get(key)
        if val:
            return val.strip()

    # 2. 搜尋 .env 檔案候選路徑
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    cwd = Path.cwd()
    script_dir = Path(__file__).resolve().parent
    candidates.extend([
        script_dir / ".env",
        cwd / ".env",
        cwd / "gemini api test" / ".env",
        script_dir.parent / ".env",
    ])

    for p in candidates:
        if p.exists() and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k in ("API_KEY", "GEMINI_API_KEY") and v:
                            return v
            except Exception:
                continue

    raise ValueError(
        "未找到 Gemini API Key！請在 .env 檔案中設定 API_KEY=xxx，或設定環境變數 GEMINI_API_KEY。"
    )


class GeminiClient:
    """Gemini 原生 REST API 多模態客戶端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.5-flash-lite",
        env_path: Optional[Union[str, Path]] = None,
    ):
        self.api_key = api_key or find_api_key(Path(env_path) if env_path else None)
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com"

    def _http_request(
        self,
        url: str,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        method: str = "GET",
    ) -> Tuple[int, Dict[str, Any], Any]:
        """封裝標準庫 HTTP 請求"""
        hdrs = headers or {}
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                body = resp.read()
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except Exception:
                    parsed = body.decode("utf-8", errors="ignore")
                return status, resp_headers, parsed
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP Error {e.code}: {e.reason}\n{err_text}") from e

    def _upload_file_resumable(
        self, file_path: Path, mime_type: str, verbose: bool = False
    ) -> Tuple[str, str]:
        """
        透過 Google Files API 可續傳上傳 (Resumable Upload)
        回傳: (file_name, file_uri)
        """
        file_size = file_path.stat().st_size
        if verbose:
            print(f"[*] [Files API] 步驟 1: 初始化上傳 ({file_size / (1024 * 1024):.2f} MB)...")

        # 1. Start Resumable Upload
        init_url = f"{self.base_url}/upload/v1beta/files?key={self.api_key}"
        init_meta = json.dumps({"file": {"display_name": file_path.name}}).encode("utf-8")
        init_hdrs = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        _, resp_hdrs, _ = self._http_request(init_url, data=init_meta, headers=init_hdrs, method="POST")
        upload_url = resp_hdrs.get("x-goog-upload-url") or resp_hdrs.get("X-Goog-Upload-URL")
        if not upload_url:
            raise RuntimeError("無法獲取 x-goog-upload-url，請確認 API 金鑰是否有效。")

        # 2. Upload Bytes
        if verbose:
            print(f"[*] [Files API] 步驟 2: 正在上傳二進位檔案資料...")
        upload_hdrs = {
            "Content-Length": str(file_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        _, _, upload_res = self._http_request(
            upload_url, data=file_path.read_bytes(), headers=upload_hdrs, method="POST"
        )

        file_info = upload_res.get("file", {})
        file_name = file_info.get("name")
        file_uri = file_info.get("uri")
        state = file_info.get("state")

        # 3. 輪詢狀態直到 ACTIVE (若需後端轉碼處理)
        if verbose:
            print(f"[*] [Files API] 步驟 3: 等待檔案處理 (當前: {state})...")

        while state == "PROCESSING":
            time.sleep(2)
            poll_url = f"{self.base_url}/v1beta/{file_name}?key={self.api_key}"
            _, _, poll_res = self._http_request(poll_url)
            state = poll_res.get("state")
            if verbose:
                print(f"    - 輪詢狀態: {state}")

        if state != "ACTIVE":
            raise RuntimeError(f"檔案上傳後處理失敗，最終狀態: {state}")

        if verbose:
            print(f"[*] [Files API] 上傳就緒: {file_name}")

        return file_name, file_uri

    def generate(
        self,
        prompt: str,
        media_path: Optional[Union[str, Path]] = None,
        mime_type: Optional[str] = None,
        method: str = "auto",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        verbose: bool = False,
    ) -> str:
        """
        核心多模態生成接口
        :param prompt: 文字提示詞
        :param media_path: 影片、音訊、圖片或文件檔案路徑 (可為 None)
        :param mime_type: 媒體 MIME-Type (若 None 則自動偵測)
        :param method: 'auto' | 'inline' | 'files_api'
        :param model: 覆寫預設模型
        :param system_instruction: 系統指示詞
        :param temperature: 溫度參數 (0.0 ~ 2.0)
        :param verbose: 是否列印詳細進度
        :return: 模型生成的字串內容
        """
        target_model = model or self.model
        parts = []

        # 處理多媒體輸入
        if media_path:
            p = Path(media_path).resolve()
            if not p.exists():
                raise FileNotFoundError(f"找不到指定檔案: {p}")

            detected_mime = mime_type or detect_mime_type(p)
            file_size = p.stat().st_size

            # 決策傳輸方式
            chosen_method = method.lower()
            if chosen_method == "auto":
                chosen_method = "inline" if file_size <= INLINE_MAX_BYTES else "files_api"

            if chosen_method == "inline":
                if verbose:
                    print(f"[*] 使用 inline_data (Base64) 模式，大小: {file_size / (1024 * 1024):.2f} MB")
                b64_data = base64.b64encode(p.read_bytes()).decode("utf-8")
                parts.append({
                    "inline_data": {
                        "mime_type": detected_mime,
                        "data": b64_data,
                    }
                })
            elif chosen_method == "files_api":
                _, file_uri = self._upload_file_resumable(p, detected_mime, verbose=verbose)
                parts.append({
                    "file_data": {
                        "mime_type": detected_mime,
                        "file_uri": file_uri,
                    }
                })
            else:
                raise ValueError(f"不支援的傳輸模式: {method} (僅支援 auto, inline, files_api)")

        # 加入文字 Prompt
        if prompt:
            parts.append({"text": prompt})

        if not parts:
            raise ValueError("必須提供 prompt 或 media_path 其中之一！")

        payload: Dict[str, Any] = {"contents": [{"parts": parts}]}

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = float(temperature)
        if generation_config:
            payload["generationConfig"] = generation_config

        url = f"{self.base_url}/v1beta/models/{target_model}:generateContent?key={self.api_key}"
        if verbose:
            print(f"[*] 發送 REST 請求至模型 {target_model}...")

        start_time = time.time()
        _, _, res = self._http_request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        elapsed = time.time() - start_time
        if verbose:
            print(f"[*] 模型推論完成，耗時: {elapsed:.2f} 秒")

        try:
            return res["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as err:
            return f"解析回應結構失敗: {err}\n原始回應: {json.dumps(res, indent=2, ensure_ascii=False)}"

    # 語意化快捷呼叫方法
    def text(self, prompt: str, **kwargs) -> str:
        """純文字問答"""
        return self.generate(prompt=prompt, media_path=None, **kwargs)

    def audio(self, prompt: str, audio_path: Union[str, Path], **kwargs) -> str:
        """音訊問答 / 語音辨識 / 聲音分析"""
        return self.generate(prompt=prompt, media_path=audio_path, **kwargs)

    def video(self, prompt: str, video_path: Union[str, Path], **kwargs) -> str:
        """影片分析 / 視覺理解"""
        return self.generate(prompt=prompt, media_path=video_path, **kwargs)

    def image(self, prompt: str, image_path: Union[str, Path], **kwargs) -> str:
        """圖片識別 / OCR / 圖像分析"""
        return self.generate(prompt=prompt, media_path=image_path, **kwargs)


def main():
    parser = argparse.ArgumentParser(
        description="Gemini REST API 多模態通用呼叫工具 (支援影片/音訊/文字/圖片)"
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="輸入提示詞 (Prompt)。若未提供且指定了媒體檔案，將使用預設提示詞。",
    )
    parser.add_argument(
        "-f", "--file",
        dest="media_file",
        type=str,
        default=None,
        help="輸入媒體路徑 (通用：影片、音訊、圖片、PDF皆可)",
    )
    parser.add_argument(
        "-v", "--video",
        dest="video_file",
        type=str,
        default=None,
        help="指定影片檔案路徑",
    )
    parser.add_argument(
        "-a", "--audio",
        dest="audio_file",
        type=str,
        default=None,
        help="指定音訊檔案路徑",
    )
    parser.add_argument(
        "-i", "--image",
        dest="image_file",
        type=str,
        default=None,
        help="指定圖片檔案路徑",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default="gemini-3.5-flash-lite",
        help="指定 Gemini 模型 (預設: gemini-3.5-flash-lite)",
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["auto", "inline", "files_api"],
        default="auto",
        help="傳輸方式: auto (預設，<=20MB 自動用 inline，大檔用 files_api), inline, files_api",
    )
    parser.add_argument(
        "--sys",
        dest="system_instruction",
        type=str,
        default=None,
        help="系統指令 (System Instruction)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="顯示連線與處理進度細節",
    )

    args = parser.parse_args()

    # 彙整檔案路徑
    media_path = args.media_file or args.video_file or args.audio_file or args.image_file

    # 若未給 prompt，根據檔案類型給予適當預設
    prompt = args.prompt
    if not prompt:
        if args.video_file:
            prompt = "請詳細描述並結構化分析這段影片中發生的事件、登場物體、動作與結果。以繁體中文回答。"
        elif args.audio_file:
            prompt = "請詳細辨識並描述這段音訊中的內容（人聲語音、環境聲音、音效細節等）。以繁體中文回答。"
        elif args.image_file:
            prompt = "請詳細描述這張圖片的畫面內容與細節。以繁體中文回答。"
        elif media_path:
            prompt = "請詳細分析這個多媒體檔案的內容。以繁體中文回答。"
        else:
            prompt = "你好！請簡短自我介紹。"

    try:
        client = GeminiClient(model=args.model)
    except Exception as e:
        print(f"初始化失敗: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"Gemini 模型: {args.model}")
    print(f"傳輸模式   : {args.method}")
    if media_path:
        print(f"媒體檔案   : {media_path} ({detect_mime_type(media_path)})")
    print(f"提示詞 (Prompt): {prompt}")
    print("=" * 60)

    try:
        result = client.generate(
            prompt=prompt,
            media_path=media_path,
            method=args.method,
            system_instruction=args.system_instruction,
            verbose=args.verbose or bool(media_path),
        )
        print("\n" + "=" * 25 + " 模型回答 " + "=" * 25)
        print(result)
        print("=" * 58)
    except Exception as e:
        print(f"\n[呼叫錯誤]: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
