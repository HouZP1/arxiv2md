import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://arxiv2md.org/api/markdown"
TIMEOUT = 180  # 秒


def extract_arxiv_id(filename):
    """识别 arXiv 编号及可选的版本后缀。"""
    version = ""
    match = re.search(r"v[1-9][0-9]*$", filename)

    if match:
        version = match.group()
        filename = filename[:match.start()]

    if re.fullmatch(r"[0-9]+", filename):
        return f"hep-ph/{filename}{version}"

    if filename.split("-")[0] == "hep":
        match = re.fullmatch(
            r"(hep-[A-Za-z]+)[-_]?([0-9]+)", filename
        )
        if match:
            return f"{match.group(1)}/{match.group(2)}{version}"
        raise ValueError("无法解析 hep 类编号")

    if re.fullmatch(r"[0-9]{4}\.[0-9]+", filename):
        return filename + version

    raise ValueError("文件名不符合 arXiv 编号规则")


def fetch_markdown(arxiv_id):
    url = f"{API_URL}?{urlencode({'url': arxiv_id})}"
    request = Request(
        url,
        headers={
            "User-Agent": "arxiv-markdown-downloader/1.0",
            "Accept": "text/markdown, text/plain, application/json",
        },
    )

    with urlopen(request, timeout=TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        encoding = response.headers.get_content_charset() or "utf-8"
        text = response.read().decode(encoding).lstrip("\ufeff")

    if not text.strip():
        raise ValueError("接口返回空内容，未找到 Markdown")

    if "text/html" in content_type or re.match(
        r"\s*(?:<!doctype\s+html|<html\b)", text, re.I
    ):
        raise ValueError("接口返回 HTML 页面，未找到 Markdown")

    if "json" in content_type:
        data = json.loads(text)

        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            if data.get("error") or data.get("success") is False:
                raise ValueError(
                    f"接口错误：{data.get('error') or data.get('message') or data}"
                )

            text = data.get("markdown")
            if text is None and isinstance(data.get("data"), dict):
                text = data["data"].get("markdown")
            if text is None:
                text = data.get("content")
        else:
            text = None

        if not isinstance(text, str) or not text.strip():
            raise ValueError("接口响应中未找到 Markdown 文本")

    return text


def main():
    directory = Path.cwd()
    pdf_files = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )

    if not pdf_files:
        print("当前目录下未找到 PDF 文件。")
        return 0

    succeeded = failed = skipped = 0

    for pdf in pdf_files:
        try:
            arxiv_id = extract_arxiv_id(pdf.stem)
            output = directory / f"{arxiv_id.replace('/', '_')}.txt"

            # 在调用 API 前检查，已有对应文件则跳过。
            if output.exists():
                print(f"[跳过] {pdf.name}：{output.name} 已存在")
                skipped += 1
                continue

            markdown = fetch_markdown(arxiv_id)
            output.write_text(markdown, encoding="utf-8")

            print(f"[成功] {pdf.name} -> {output.name}")
            succeeded += 1

        except HTTPError as exc:
            print(
                f"[错误] {pdf.name}：HTTP {exc.code}，"
                f"未能获取 Markdown（{exc.reason}）",
                file=sys.stderr,
            )
            failed += 1

        except Exception as exc:
            print(f"[错误] {pdf.name}：{exc}", file=sys.stderr)
            failed += 1

    print(
        f"\n处理完成：成功 {succeeded} 个，"
        f"跳过 {skipped} 个，失败 {failed} 个。"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())