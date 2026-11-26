#!/usr/bin/env python3
"""협객풍운전 세이브 에디터 (Tale of Wuxia Save Editor v1.0.1) 단일 HTML 빌드 스크립트."""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VERSION = "1.0.1"
NAME = "TaleOfWuxiaSaveEditor"
SRC_FILE = BASE_DIR / "src" / "editor-page.html"
DIST_DIR = BASE_DIR / "dist"
OUT_FILE = DIST_DIR / f"{NAME}-v{VERSION}.html"
SCRIPT_FILES = ["twx-codec.js", "catalog-data.js", "editor-core.js", "editor-ui.js"]
MAX_BYTES = 10 * 1024 * 1024
CSP_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)

CSP_META_RE = re.compile(
    r"<meta\b[^>]*http-equiv\s*=\s*[\"']Content-Security-Policy[\"'][^>]*>",
    re.IGNORECASE,
)
LEFTOVER_SCRIPT_RE = re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE)
URL_RE = re.compile(
    r"(?:https?://|ftp://|wss?://)|(?<![:/])//(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}",
    re.IGNORECASE,
)
HANZI_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
KANA_RE = re.compile(r"[\u3040-\u30FF\u31F0-\u31FF\uFF66-\uFF9F]")
SINKS_RE = re.compile(
    r"\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b"
    r"|\bdocument\.write\s*\("
    r"|\beval\s*\("
    r"|\bnew\s+Function\s*\("
)
PATH_RE = re.compile(r"/home/|c:\\users\\", re.IGNORECASE)


def _escape_script(content: str) -> str:
    return content.replace("</script", "<\\/script").replace("</SCRIPT", "<\\/SCRIPT")


def _ensure_csp(html: str) -> str:
    tag = f'<meta http-equiv="Content-Security-Policy" content="{CSP_POLICY}">'
    m = CSP_META_RE.search(html)
    if m:
        existing = m.group(0)
        if "default-src 'none'" in existing and "connect-src 'none'" in existing:
            return html
        return html[: m.start()] + tag + html[m.end():]
    m = re.search(r"<meta\b[^>]*charset[^>]*>", html, re.IGNORECASE)
    if m:
        return html[: m.end()] + "\n" + tag + html[m.end():]
    return tag + "\n" + html


def _inline_one(html: str, name: str, src_dir: Path) -> str:
    pattern = re.compile(
        r"<script\b[^>]*\bsrc\s*=\s*[\"'](?:[^\"']*/)?"
        + re.escape(name)
        + r"[\"'][^>]*>\s*</script\s*>",
        re.IGNORECASE,
    )
    path = src_dir / name
    if not path.exists():
        raise FileNotFoundError(f"인라인 대상 스크립트를 찾을 수 없습니다: {path}")
    content = _escape_script(path.read_text(encoding="utf-8"))
    if not pattern.search(html):
        raise ValueError(f"HTML에서 다음 스크립트 참조를 찾지 못했습니다: {name}")
    return pattern.sub(lambda _: f"<script>\n{content}\n</script>", html, count=1)


def build() -> str:
    html = SRC_FILE.read_text(encoding="utf-8")
    src_dir = SRC_FILE.parent
    for name in SCRIPT_FILES:
        html = _inline_one(html, name, src_dir)
    return _ensure_csp(html)


def verify(html: str) -> list[str]:
    errs: list[str] = []
    if LEFTOVER_SCRIPT_RE.search(html):
        errs.append("[오류] 인라인되지 않은 <script src=...> 태그가 남아 있습니다.")
    csp = CSP_META_RE.search(html)
    if (
        not csp
        or "default-src 'none'" not in csp.group(0)
        or "connect-src 'none'" not in csp.group(0)
    ):
        errs.append("[오류] Content-Security-Policy 메타 태그(default-src 'none' / connect-src 'none')가 누락되었습니다.")
    urls = URL_RE.findall(html)
    if urls:
        errs.append(f"[오류] 외부 URL이 {len(urls)}개 포함되어 있습니다. 예: {urls[0]}")
    hanzi = HANZI_RE.findall(html)
    if hanzi:
        errs.append(f"[오류] 리터럴 한자가 {len(hanzi)}개 포함되어 있습니다. 예: U+{ord(hanzi[0]):04X}")
    kana = KANA_RE.findall(html)
    if kana:
        errs.append(f"[오류] 리터럴 가나가 {len(kana)}개 포함되어 있습니다. 예: U+{ord(kana[0]):04X}")
    sinks = SINKS_RE.findall(html)
    if sinks:
        errs.append(f"[오류] 안전하지 않은 DOM/코드 싱크가 발견되었습니다: {sinks[0]}")
    if PATH_RE.search(html):
        errs.append("[오류] 개인 경로 문자열이 포함되어 있습니다.")
    size = len(html.encode("utf-8"))
    if size > MAX_BYTES:
        errs.append(f"[오류] UTF-8 바이트 길이가 {size:,}B로 10 MiB를 초과합니다.")
    return errs


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="기존 dist 산출물만 검증합니다.")
    args = parser.parse_args(argv)

    if args.check:
        if not OUT_FILE.exists():
            print(f"[오류] 검증 대상 파일이 없습니다: {OUT_FILE}", file=sys.stderr)
            return 1
        raw_bytes = OUT_FILE.read_bytes()
        html = raw_bytes.decode("utf-8")
        errs = verify(html)
        if raw_bytes != build().encode("utf-8"):
            errs.append("[오류] dist 산출물이 현재 src/* 재빌드 결과와 일치하지 않습니다.")
        if errs:
            for e in errs:
                print(e, file=sys.stderr)
            return 1
        print(f"[성공] 검증 통과: {OUT_FILE} ({len(html.encode('utf-8')):,} B)")
        return 0

    html = build()
    errs = verify(html)
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    _atomic_write(OUT_FILE, html.encode("utf-8"))
    print(f"[성공] 빌드 완료: {OUT_FILE} ({len(html.encode('utf-8')):,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
