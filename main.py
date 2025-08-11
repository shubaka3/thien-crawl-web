from fastapi import FastAPI, UploadFile, Form
from utils import crawl_site, ocr_image
import shutil
import tempfile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Web Crawler + OCR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Hoặc chỉ cho phép domain cụ thể
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Crawl endpoint
@app.get("/crawl")
def crawl(url: str, depth: int = None):
    if depth is None:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        depth = int(os.getenv("MAX_DEPTH", 3))
    depth = min(depth, 5)  # Giới hạn max depth = 5
    results = crawl_site(url, depth)
    return {"depth": depth, "pages": results}

# OCR endpoint
@app.post("/ocr")
async def ocr(file: UploadFile):
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    grouped_text = ocr_image(tmp_path)
    return {"lines": grouped_text}
