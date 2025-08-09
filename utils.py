import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from collections import deque
from fastapi import FastAPI
import os
from urllib.parse import urljoin, urlparse, urldefrag
import hashlib
import difflib


load_dotenv()

MAX_DEPTH = int(os.getenv("MAX_DEPTH", 2))
OCR_API_URL = os.getenv("OCR_API_URL")
OCR_MODEL = os.getenv("OCR_MODEL")
OCR_LANG = os.getenv("OCR_LANG")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 5))

app = FastAPI()

# ===== URL chuẩn hóa =====
def normalize_url(url):
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    clean_query = "&".join(
        q for q in parsed.query.split("&")
        if q and not q.startswith("utm_") and not q.startswith("fbclid")
    )
    return parsed._replace(query=clean_query).geturl().rstrip("/")


def is_valid_link(base_domain, link):
    parsed = urlparse(link)
    if parsed.netloc and parsed.netloc != base_domain:
        return False
    skip_ext = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".xml", ".css", ".js", ".zip")
    if any(parsed.path.lower().endswith(ext) for ext in skip_ext):
        return False
    return True


def hash_block(title, content):
    key = (title + content).encode("utf-8")
    return hashlib.md5(key).hexdigest()


def is_title_tag(tag):
    if tag.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        return True
    class_attr = tag.get("class") or []
    class_text = " ".join(class_attr).lower()
    keywords = ["title", "heading", "header", "post-title", "entry-title", "caption", "subtitle"]
    return any(k in class_text for k in keywords)

def remove_long_parent_blocks(blocks, containment_threshold=0.95, length_ratio_threshold=1.2, max_length=3000):
    filtered = []
    for i, block_i in enumerate(blocks):
        content_i = block_i["content"]
        len_i = len(content_i)

        # Loại bỏ thô block quá dài
        if len_i > max_length:
            continue

        is_parent = False
        for j, block_j in enumerate(blocks):
            if i == j:
                continue
            content_j = block_j["content"]
            len_j = len(content_j)
            if len_i <= len_j * length_ratio_threshold:
                continue

            # containment đơn giản
            if content_j in content_i:
                is_parent = True
                break

            ratio = difflib.SequenceMatcher(None, content_i, content_j).ratio()
            if ratio > containment_threshold and len_i > len_j * length_ratio_threshold:
                is_parent = True
                break

        if not is_parent:
            filtered.append(block_i)
    return filtered

def filter_similar_blocks(blocks, threshold=0.9):
    filtered = []
    for block in blocks:
        content = block["content"]
        is_dup = False
        for fb in filtered:
            ratio = difflib.SequenceMatcher(None, content, fb["content"]).ratio()
            if ratio > threshold or content in fb["content"] or fb["content"] in content:
                is_dup = True
                break
        if not is_dup:
            filtered.append(block)
    return filtered

def extract_content_blocks(html: str, depth: int = 0):
    soup = BeautifulSoup(html, "html.parser")

    # Loại bỏ vùng không cần thiết
    for sel in ["header", "nav", "footer", ".sidebar", ".breadcrumb", ".pagination", ".ads", ".advertisement", "script", "style"]:
        for tag in soup.select(sel):
            tag.decompose()

    main_area = soup.find("main") or soup.find("article") or soup.select_one(".content, .post")
    if main_area:
        soup = BeautifulSoup(str(main_area), "html.parser")

    candidates = soup.find_all(["h1","h2","h3","h4","h5","h6","p","li","div","span"])
    blocks = []
    content_hashes = set()

    i = len(candidates) - 1
    while i >= 0:
        elem = candidates[i]
        text = elem.get_text(" ", strip=True)
        if not text:
            i -= 1
            continue

        # Xác định title
        is_title = False
        if elem.name in ["h1","h2","h3","h4","h5","h6"]:
            is_title = True
        else:
            class_attr = " ".join(elem.get("class") or [])
            if any(k in class_attr.lower() for k in ["title","header","heading","caption","subtitle"]) and len(text.split()) <= 10:
                is_title = True

        if is_title:
            # Lấy content bên dưới title
            content_texts = []
            for j in range(i+1, len(candidates)):
                c = candidates[j]
                c_text = c.get_text(" ", strip=True)
                if not c_text:
                    continue
                # Gặp title khác thì dừng
                if c.name in ["h1","h2","h3","h4","h5","h6"]:
                    break
                content_texts.append(c_text)
                if len(content_texts) >= 5:
                    break

            full_content = " ".join(content_texts).strip()
            if full_content:
                h = hashlib.md5(full_content.encode("utf-8")).hexdigest()
                if h not in content_hashes:
                    content_hashes.add(h)
                    blocks.append({
                        "title": text,
                        "content": full_content,
                        "elem": elem
                    })
        i -= 1

    # Lọc bỏ các block "cha" chứa block con
    filtered_blocks = []
    for block in blocks:
        is_parent = False
        for other in blocks:
            if other == block:
                continue
            # Nếu block['elem'] chứa other['elem'] => block là cha
            if block["elem"].find(other["elem"]) is not None:
                is_parent = True
                break
        if not is_parent:
            filtered_blocks.append(block)

    # Bỏ elem trước khi trả về
    for b in filtered_blocks:
        b.pop("elem", None)

    # Đảo lại theo thứ tự xuất hiện trong html (từ trên xuống)
    filtered_blocks.reverse()
    blocks = remove_long_parent_blocks(filtered_blocks)
    filtered_blocks = filter_similar_blocks(blocks)
    return filtered_blocks

def crawl_site(start_url, max_depth=2):
    base_domain = urlparse(start_url).netloc
    visited = set()
    queue = deque([(normalize_url(start_url), 0)])
    results = []

    while queue:
        url, depth = queue.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        try:
            print(f"[{depth}] Crawling: {url}")
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            if "text/html" not in r.headers.get("Content-Type", ""):
                continue
            blocks = extract_content_blocks(r.text, depth=depth)
            results.append({"url": url, "blocks": blocks})

            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            continue

        # Lấy link hợp lệ để crawl tiếp
        for a in soup.find_all("a", href=True):
            full_url = urljoin(url, a["href"])
            full_url = normalize_url(full_url)
            if is_valid_link(base_domain, full_url) and full_url not in visited:
                queue.append((full_url, depth + 1))

    return results

# ======= OCR PROCESSING =======
def group_ocr_text(ocr_data: dict, y_threshold: int = 15):
    """
    Gộp các text nếu tọa độ y gần nhau (cùng 1 dòng)
    """
    lines = {}
    for item in ocr_data.get("result", []):
        y_center = (item["box"][0][1] + item["box"][2][1]) / 2
        # Tìm dòng gần nhất
        found_line = None
        for line_y in lines.keys():
            if abs(line_y - y_center) <= y_threshold:
                found_line = line_y
                break
        if found_line is None:
            lines[y_center] = []
            found_line = y_center
        lines[found_line].append(item["text"])
    # Gộp text từng dòng
    return [" ".join(parts) for _, parts in sorted(lines.items())]

def ocr_image(file_path: str):
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"model": OCR_MODEL, "lang": OCR_LANG}
        r = requests.post(OCR_API_URL, files=files, data=data)
        r.raise_for_status()
        return group_ocr_text(r.json())

# # ======= API ENDPOINT =======
# @app.get("/crawl")
# def crawl(url: str, depth: int = 2):
#     if depth > MAX_DEPTH:
#         depth = MAX_DEPTH
#     results = crawl_site(url, depth)
#     return {"count": len(results), "data": results}
