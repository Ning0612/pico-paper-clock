#!/usr/bin/env python3
"""
tools/build_html.py  —  HTML source → src/html/*.bin 建置工具

工作流程
--------
  1. 在 tools/html_src/*.html 編輯人類可讀的 HTML 原始碼
  2. python tools/build_html.py            # 建置所有 .bin
  3. python upload.py                      # 部署到裝置

初始化（首次使用）
------------------
  python tools/build_html.py --init        # 從現有 .bin 提取出 html_src/*.html

格式規則
--------
  - html_src 中的 .html 是完整的頁面源碼，不包含 HTTP 回應 header
  - 建置後的 .bin 是 gzip payload；HTTP header 由韌體統一添加

最小化策略
----------
  1. 移除 HTML 註解 <!-- ... -->（支援跨行）
  2. 每行去除前後空白
  3. 移除空行
  4. 相鄰行直接串接（HTML/CSS/JS 中換行不影響語意）
  5. 若舊源碼仍以 HTTP response header 開頭，建置時移除該 header

壓縮策略
--------
  - 使用 deterministic gzip（mtime=0），讓相同源碼產生穩定的 binary 產物
  - 瀏覽器透過 HTTP Content-Encoding: gzip 自動解壓
"""

import argparse
import gzip
import os
import re
import sys

SRC_DIR = os.path.join(os.path.dirname(__file__), "html_src")
BIN_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "html")
GZIP_OS_UNKNOWN = 255


def minify(text: str) -> str:
    """最小化 HTML：移除註解、折疊空白行，保留語意。"""
    # 移除 HTML 註解（不跨越 <!-- --> 內的 JS/CSS 字串，只針對 HTML 層級）
    # 使用非貪婪匹配以避免跨越多個注釋
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # 舊版 reset/success 源碼可能自己攜帶 HTTP response header；
    # 現在 header 由韌體統一發送，建置時只保留 HTML body。
    if text.startswith("HTTP/"):
        header_and_body = re.split(r"\r?\n\r?\n", text, maxsplit=1)
        if len(header_and_body) == 2:
            text = header_and_body[1]

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)

    return "".join(lines)


def deterministic_gzip(data: bytes) -> bytes:
    """Return a gzip payload whose header is stable across build platforms."""
    output = bytearray(gzip.compress(data, compresslevel=9, mtime=0))
    if len(output) < 10 or output[:3] != b"\x1f\x8b\x08":
        raise ValueError("gzip.compress returned an invalid gzip header")

    # Python may delegate mtime=0 compression to zlib, which writes the host
    # operating-system code into the gzip header.  Keep generated .bin files
    # identical on Windows and Linux by using the standard unknown code.
    output[9] = GZIP_OS_UNKNOWN
    return bytes(output)


def build_one(src_path: str, bin_path: str) -> int:
    """建置單一 HTML 源碼為 .bin，回傳輸出位元組數。"""
    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()

    output = deterministic_gzip(minify(source).encode("utf-8"))

    os.makedirs(os.path.dirname(bin_path), exist_ok=True)
    with open(bin_path, "wb") as f:
        f.write(output)

    return len(output)


def build_all(names: list[str] | None = None, verbose: bool = True) -> bool:
    """建置所有（或指定的）HTML 源碼。"""
    if not os.path.isdir(SRC_DIR):
        print(f"[錯誤] 源碼目錄不存在：{SRC_DIR}")
        print("請先執行 --init 從現有 .bin 提取源碼，或自行建立 html_src/*.html")
        return False

    html_files = [f for f in os.listdir(SRC_DIR) if f.endswith(".html")]
    if not html_files:
        print(f"[警告] {SRC_DIR} 中沒有 .html 檔案")
        return True

    if names:
        html_files = [f for f in html_files if f[:-5] in names or f in names]

    ok = True
    for filename in sorted(html_files):
        src_path = os.path.join(SRC_DIR, filename)
        bin_name = os.path.splitext(filename)[0] + ".bin"
        bin_path = os.path.join(BIN_DIR, bin_name)
        try:
            size = build_one(src_path, bin_path)
            if verbose:
                src_size = os.path.getsize(src_path)
                ratio = (1 - size / src_size) * 100 if src_size else 0
                print(f"  {filename:<20} -> {bin_name:<20}  {src_size} -> {size} bytes ({ratio:.1f}% 減少)")
        except Exception as e:
            print(f"  [失敗] {filename}: {e}")
            ok = False

    return ok


def init_from_bins(force: bool = False) -> None:
    """從現有 .bin 提取源碼到 html_src/*.html（首次初始化用）。"""
    os.makedirs(SRC_DIR, exist_ok=True)

    if not os.path.isdir(BIN_DIR):
        print(f"[錯誤] .bin 目錄不存在：{BIN_DIR}")
        return

    bin_files = [f for f in os.listdir(BIN_DIR) if f.endswith(".bin")]
    if not bin_files:
        print(f"[警告] {BIN_DIR} 中沒有 .bin 檔案")
        return

    for bin_name in sorted(bin_files):
        html_name = os.path.splitext(bin_name)[0] + ".html"
        src_path = os.path.join(SRC_DIR, html_name)
        bin_path = os.path.join(BIN_DIR, bin_name)

        if os.path.exists(src_path) and not force:
            print(f"  跳過（已存在）：{html_name}  (使用 --force 覆寫)")
            continue

        with open(bin_path, "rb") as f:
            content = f.read()

        try:
            content = gzip.decompress(content)
        except (OSError, EOFError):
            # Accept legacy plain HTML assets during migration.
            pass

        with open(src_path, "wb") as f:  # binary write 保留原始位元組
            f.write(content)

        print(f"  提取：{bin_name} -> {html_name}  ({len(content)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HTML source → src/html/*.bin 建置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="從現有 .bin 提取源碼到 html_src/*.html（首次初始化）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="搭配 --init：強制覆寫已存在的 .html 源碼",
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="NAME",
        help="僅建置指定的 .html 或名稱（不加副檔名亦可）",
    )
    args = parser.parse_args()

    if args.init:
        print(f"[init] 從 {BIN_DIR} 提取源碼到 {SRC_DIR}")
        init_from_bins(force=args.force)
        return

    print(f"[build] {SRC_DIR} -> {BIN_DIR}")
    success = build_all(names=args.files if args.files else None)
    if not success:
        sys.exit(1)
    print("[完成]")


if __name__ == "__main__":
    main()
