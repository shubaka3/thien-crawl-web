(async () => {
  const idb = window.idb;

  // IndexedDB setup
  const db = await idb.openDB('ai-demo-db', 1, {
    upgrade(db) {
      db.createObjectStore('pages', { keyPath: 'url' });
    }
  });

  const url = location.href;

  // Lấy data từ DB nếu có
  let pageData = await db.get('pages', url);

  // Hàm crawl dữ liệu từ trang
  function crawlPage() {
    const sections = [];
    const headers = Array.from(document.querySelectorAll('h2'));
    for(let i=0; i<headers.length; i++) {
      const title = headers[i].innerText.trim();
      let content = '';
      let el = headers[i].nextElementSibling;
      while(el && el.tagName !== 'H2') {
        content += el.innerText + '\n';
        el = el.nextElementSibling;
      }
      // Tách content thành các đoạn nhỏ theo câu hoặc xuống dòng
      const paragraphs = content.split(/\. |\n/).map(p => p.trim()).filter(Boolean);
      paragraphs.forEach(p => {
        sections.push({ title, content: p });
      });
    }
    return sections;
  }

  // Load Universal Sentence Encoder Lite
  const useModel = await use.load();

  // Hàm embed text
  async function embedTexts(texts) {
    const embeddingsTensor = await useModel.embed(texts);
    const embeddings = await embeddingsTensor.array();
    embeddingsTensor.dispose();
    return embeddings;
  }

  // Nếu chưa có data, crawl + embed + lưu
  if(!pageData) {
    console.log('Chưa có data, crawl và embed');
    const sections = crawlPage();
    const texts = sections.map(s => s.content);
    const embeddings = await embedTexts(texts);
    for(let i=0; i<sections.length; i++) {
      sections[i].embedding = embeddings[i];
    }
    pageData = { url, sections };
    await db.put('pages', pageData);
  } else {
    console.log('Đã load data từ IndexedDB');
  }

  console.log(pageData.sections);

  // Hàm cosine similarity
  function cosineSim(a, b) {
    let dot=0, normA=0, normB=0;
    for(let i=0; i<a.length; i++){
      dot += a[i]*b[i];
      normA += a[i]*a[i];
      normB += b[i]*b[i];
    }
    return dot / (Math.sqrt(normA)*Math.sqrt(normB));
  }

  // Tìm đoạn gần nhất
  function findMostSimilar(queryEmbedding) {
    let bestScore = -Infinity;
    let bestSection = null;
    for(const section of pageData.sections) {
      const score = cosineSim(queryEmbedding, section.embedding);
      if(score > bestScore) {
        bestScore = score;
        bestSection = section;
      }
    }
    return bestSection;
  }

  // Giao diện tìm kiếm
  document.getElementById('searchBtn').onclick = async () => {
    const q = document.getElementById('queryInput').value.trim();
    if(!q) return alert('Nhập câu hỏi');
    const qEmbedding = (await embedTexts([q]))[0];
    const res = findMostSimilar(qEmbedding);
    document.getElementById('result').innerHTML = `
      <h3>Phân đoạn liên quan:</h3>
      <strong>Title:</strong> ${res.title}<br/>
      <p>${res.content}</p>
    `;
  };
})();
