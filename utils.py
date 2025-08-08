import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from collections import deque
from fastapi import FastAPI
import os

load_dotenv()

MAX_DEPTH = int(os.getenv("MAX_DEPTH", 3))
OCR_API_URL = os.getenv("OCR_API_URL")
OCR_MODEL = os.getenv("OCR_MODEL")
OCR_LANG = os.getenv("OCR_LANG")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 5))

app = FastAPI()

# ======= HTML CLEANING =======
def extract_content_blocks(html: str):
    """
    Tách HTML thành danh sách block: title (có thể gồm nhiều cấp) + content
    """
    soup = BeautifulSoup(html, "html.parser")

    # Xóa phần không cần
    for selector in ["header", "nav", "footer", ".ads", ".advertisement", ".sidebar", "script", "style"]:
        for tag in soup.select(selector):
            tag.decompose()

    blocks = []
    current_titles = []  # chứa nhiều cấp tiêu đề
    current_content = []

    def flush_block():
        nonlocal current_titles, current_content
        if current_titles or current_content:
            blocks.append({
                "title": " - ".join([t for t in current_titles if t]).strip(),
                "content": " ".join(current_content).strip()
            })
            current_content = []

    for elem in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "b", "p", "li", "span", "div"]):
        tag_name = elem.name.lower()
        text = elem.get_text(" ", strip=True)
        if not text:
            continue

        # Xác định đây là tiêu đề (heading, b, hoặc div ngắn)
        if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6", "b"] or (
            tag_name == "div" and len(text.split()) <= 8
        ):
            flush_block()
            current_titles.append(text)
            # Nếu là h1/h2 thì reset tiêu đề cấp dưới
            if tag_name in ["h1", "h2"]:
                current_titles = [text]
            elif tag_name in ["h3", "h4"]:
                current_titles = current_titles[:2] + [text]
            elif tag_name in ["h5", "h6"]:
                current_titles = current_titles[:3] + [text]
        else:
            current_content.append(text)

    flush_block()
    return blocks



# ======= WEB CRAWLING =======
def is_valid_link(base_domain, link):
    parsed = urlparse(link)

    # Chỉ crawl cùng domain
    if parsed.netloc and parsed.netloc != base_domain:
        return False

    # Loại bỏ các file không phải HTML
    skip_ext = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".xml", ".css", ".js", ".zip")
    if any(parsed.path.lower().endswith(ext) for ext in skip_ext):
        return False

    # Chỉ cho phép .html hoặc không có extension
    if parsed.path and "." in parsed.path and not parsed.path.endswith(".html"):
        return False

    return True

def crawl_site(start_url, max_depth=2):
    base_domain = urlparse(start_url).netloc
    visited = set()
    queue = deque([(start_url, 0)])
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
            blocks = extract_content_blocks(r.text)
            results.append({"url": url, "blocks": blocks})

            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            print(f"Error: {e}")
            continue

        for a in soup.find_all("a", href=True):
            full_url = urljoin(url, a["href"])
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

# ======= API ENDPOINT =======
@app.get("/crawl")
def crawl(url: str, depth: int = 2):
    if depth > MAX_DEPTH:
        depth = MAX_DEPTH
    results = crawl_site(url, depth)
    return {"count": len(results), "data": results}
