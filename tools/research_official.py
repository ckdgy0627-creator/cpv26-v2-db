#!/usr/bin/env python3
import io
import os
import re
import sys
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

PAGES = {
    "2026_live09": "https://cpbv-community.com2us.com/board/3/275486",
    "2026_live10": "https://cpbv-community.com2us.com/board/3/277364",
}

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}

OUT = Path("research")
IMG_DIR = OUT / "images"
OUT.mkdir(exist_ok=True)
IMG_DIR.mkdir(exist_ok=True)


def clean_text(text: str) -> str:
    lines = []
    for raw in text.replace("\x0c", "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def ocr_image(img: Image.Image) -> str:
    # Tables in official notices generally OCR better after enlargement + grayscale + contrast.
    rgb = img.convert("RGB")
    scale = 2 if max(rgb.size) < 2800 else 1
    if scale > 1:
        rgb = rgb.resize((rgb.width * scale, rgb.height * scale))
    gray = ImageOps.grayscale(rgb)
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = gray.filter(ImageFilter.SHARPEN)

    candidates = []
    for psm in (6, 11):
        try:
            txt = pytesseract.image_to_string(gray, lang="kor+eng", config=f"--oem 1 --psm {psm}")
            candidates.append(clean_text(txt))
        except Exception as e:
            candidates.append(f"[OCR ERROR psm={psm}: {e}]")

    # Prefer result with more Hangul + alphanumeric content.
    def score(t: str) -> int:
        return len(re.findall(r"[가-힣A-Za-z0-9]", t)) + 3 * len(re.findall(r"[가-힣]", t))
    return max(candidates, key=score) if candidates else ""


def image_urls_from_page(page_url: str):
    r = requests.get(page_url, headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    seen = set()
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if not src:
            continue
        u = urljoin(page_url, src)
        if u in seen:
            continue
        seen.add(u)
        # Keep community-upload images, skip tiny UI/icon assets.
        low = u.lower()
        if any(x in low for x in ("upload/", "community_cpbv", ".png", ".jpg", ".jpeg", ".webp")):
            urls.append(u)
    return urls


def download_image(url: str):
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "image" not in ctype.lower() and len(r.content) < 2000:
        raise RuntimeError(f"not image: {ctype}, {len(r.content)} bytes")
    img = Image.open(io.BytesIO(r.content))
    return img, r.content


def main():
    report = [
        "# 컴프야V26 공식 Live 공지 이미지 OCR 리서치",
        "",
        "자동 수집 결과입니다. OCR 결과는 후보 추출용이며 DB 확정 전 공식 공지/게임 데이터와 교차 검증해야 합니다.",
        "",
    ]

    downloaded = 0
    for key, page in PAGES.items():
        report += [f"## {key}", f"- source: {page}", ""]
        try:
            urls = image_urls_from_page(page)
        except Exception as e:
            report += [f"PAGE ERROR: {e}", ""]
            continue

        report.append(f"발견 이미지: {len(urls)}개")
        report.append("")
        for idx, url in enumerate(urls, 1):
            try:
                img, raw = download_image(url)
                # Avoid logos/icons that are clearly not tables/screenshots.
                if img.width < 300 or img.height < 120:
                    continue
                sha = hashlib.sha256(raw).hexdigest()
                ext = ".png" if "png" in (img.format or "").lower() else ".jpg"
                fname = f"{key}_{idx:02d}_{sha[:10]}{ext}"
                path = IMG_DIR / fname
                path.write_bytes(raw)
                downloaded += 1
                text = ocr_image(img)
                report += [
                    f"### image {idx}",
                    f"- url: {url}",
                    f"- file: {path.as_posix()}",
                    f"- size: {img.width}x{img.height}",
                    f"- sha256: {sha}",
                    "```text",
                    text[:30000],
                    "```",
                    "",
                ]
            except Exception as e:
                report += [f"### image {idx}", f"- url: {url}", f"- ERROR: {e}", ""]

    (OUT / "official_ocr.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote research/official_ocr.md; downloaded={downloaded}")
    if downloaded == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
