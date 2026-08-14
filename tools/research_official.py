#!/usr/bin/env python3
import io
import json
import re
import sys
import hashlib
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

BASE = "https://cpbv-community.com2us.com"
UPDATE_BOARD = f"{BASE}/board/3"
UPDATE_LIST_API = f"{BASE}/board/list/getBoardContents"

# Known anchors are always kept so historical V2 launch/10th update evidence is not lost.
KNOWN_PAGES = {
    "2026_live09": f"{BASE}/board/3/275486",
    "2026_live10": f"{BASE}/board/3/277364",
}

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    "Referer": UPDATE_BOARD,
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
    rgb = img.convert("RGB")
    scale = 2 if max(rgb.size) < 2800 else 1
    if scale > 1:
        rgb = rgb.resize((rgb.width * scale, rgb.height * scale))
    gray = ImageOps.grayscale(rgb)
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = gray.filter(ImageFilter.SHARPEN)

    candidates = []
    for psm in (6, 11, 4):
        try:
            txt = pytesseract.image_to_string(gray, lang="kor+eng", config=f"--oem 1 --psm {psm}")
            candidates.append(clean_text(txt))
        except Exception as e:
            candidates.append(f"[OCR ERROR psm={psm}: {e}]")

    def score(t: str) -> int:
        return len(re.findall(r"[가-힣A-Za-z0-9]", t)) + 3 * len(re.findall(r"[가-힣]", t))
    return max(candidates, key=score) if candidates else ""


def discover_update_posts(limit=60):
    payload = {
        "e_type": "board1",
        "idx": "3",
        "header": "",
        "lang": "ko",
        "selectType": "1",
        "page_size": str(limit),
        "page_num": "1",
        "is_mobile": "0",
        "viewChk": "LIST",
    }
    r = requests.post(UPDATE_LIST_API, headers=UA, data=payload, timeout=30)
    r.raise_for_status()
    root = r.json()
    if root.get("ret_code") != 100:
        raise RuntimeError(f"update list ret_code={root.get('ret_code')}")
    posts=[]
    for item in root.get("data", []):
        title = re.sub(r"\s+", " ", str(item.get("title", ""))).strip()
        idx = str(item.get("idx", "")).strip()
        regdate = str(item.get("regdate", "")).strip()
        if not idx or not title:
            continue
        # Current/future Live updates, V1/V2/V3 card additions, and position-change notices.
        interesting = any(token.lower() in title.lower() for token in (
            "live 업데이트", "live카드", "live 카드", "라이브 업데이트",
            "v1 라이브", "v2 라이브", "v3 라이브", "포지션 변경"
        ))
        if not interesting:
            continue
        # Keep current season and newer. Historical anchors are added separately below.
        if regdate and regdate[:4].isdigit() and int(regdate[:4]) < 2026:
            continue
        posts.append({
            "idx": idx,
            "title": title,
            "regdate": regdate,
            "url": f"{BASE}/board/3/{idx}",
        })
    return posts


def image_urls_from_page(page_url: str):
    r = requests.get(page_url, headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    urls=[]; seen=set()
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if not src:
            continue
        u = urljoin(page_url, src)
        if u in seen:
            continue
        seen.add(u)
        # Only actual community uploaded content; skip BI/background/UI assets.
        if "/upload/" in u.lower():
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


def page_key_from_post(post):
    title = post["title"]
    no = re.search(r"(\d+)차\s*(?:Live|LIVE|live)\s*업데이트", title, re.I)
    v = re.search(r"2026\s*년?\s*V([123])|\bV([123])\b", title, re.I)
    bits=["2026"]
    if no: bits.append(f"live{int(no.group(1)):02d}")
    if v: bits.append(f"v{v.group(1) or v.group(2)}")
    bits.append(post["idx"])
    return "_".join(bits)


def main():
    discovered=[]
    discovery_error=None
    try:
        discovered=discover_update_posts()
    except Exception as e:
        discovery_error=str(e)

    (OUT / "latest_update_posts.json").write_text(
        json.dumps({"posts":discovered,"error":discovery_error}, ensure_ascii=False, indent=2)+"\n",
        encoding="utf-8"
    )

    pages=dict(KNOWN_PAGES)
    # OCR only the most recent 12 relevant current-season posts each run to bound runtime.
    for post in discovered[:12]:
        pages[page_key_from_post(post)] = post["url"]

    report = [
        "# 컴프야V26 공식 Live 공지 이미지 OCR 리서치",
        "",
        "자동 수집 결과입니다. OCR은 후보 추출용이며, DB 확정은 공식 원문/인게임 카드와 교차 검증한 값만 사용합니다.",
        "검증 실패/애매한 OCR 값은 cards DB에 자동 반영하지 않습니다.",
        "",
        f"- 자동 발견 관련 게시글: {len(discovered)}개",
        f"- discovery error: {discovery_error or '없음'}",
        "",
    ]

    downloaded=0
    for key,page in pages.items():
        report += [f"## {key}", f"- source: {page}", ""]
        try:
            urls=image_urls_from_page(page)
        except Exception as e:
            report += [f"PAGE ERROR: {e}", ""]
            continue

        report.append(f"업로드 이미지: {len(urls)}개")
        report.append("")
        for idx,url in enumerate(urls,1):
            try:
                img,raw=download_image(url)
                # Tiny profile/icons are not useful tables/cards.
                if img.width < 300 or img.height < 120:
                    continue
                sha=hashlib.sha256(raw).hexdigest()
                ext = ".png" if "png" in (img.format or "").lower() else ".jpg"
                safe_key=re.sub(r"[^A-Za-z0-9_\-]", "_", key)
                fname=f"{safe_key}_{idx:02d}_{sha[:10]}{ext}"
                path=IMG_DIR/fname
                path.write_bytes(raw)
                downloaded += 1
                text=ocr_image(img)
                report += [
                    f"### image {idx}",
                    f"- url: {url}",
                    f"- file: {path.as_posix()}",
                    f"- size: {img.width}x{img.height}",
                    f"- sha256: {sha}",
                    "```text", text[:30000], "```", "",
                ]
            except Exception as e:
                report += [f"### image {idx}", f"- url: {url}", f"- ERROR: {e}", ""]

    (OUT / "official_ocr.md").write_text("\n".join(report),encoding="utf-8")
    print(f"Wrote research/official_ocr.md; discovered={len(discovered)} downloaded={downloaded}")
    if downloaded == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
