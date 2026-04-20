"""
CatchTable Brand Review Tool
----------------------------
- Dark theme UI (per CatchTable brand T&M guide)
- Real Gemini API integration (gemini-1.5-flash) with graceful fallback
- Single-file Flask app (HTML embedded) to avoid path/deploy issues
"""

import os
import json
import base64
import re
import logging
import requests
from flask import Flask, request, jsonify, Response

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("brand-review")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# Known-available multimodal models for this API key (verified via ListModels).
# First successful response wins; failures fall through to the next candidate.
_DEFAULT_MODELS = "gemini-2.5-flash,gemini-2.0-flash,gemini-flash-latest,gemini-pro-latest"
GEMINI_MODELS = [m.strip() for m in os.environ.get("GEMINI_MODEL", _DEFAULT_MODELS).split(",") if m.strip()]
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

# ---------------------------------------------------------------------------
# Brand guide prompt (embedded so it always ships with the app)
# ---------------------------------------------------------------------------
BRAND_GUIDE = """
[CatchTable Brand Tone & Manner Guide]

1. Visual tone
   - Mood: 세련되고 미식적인(refined, culinary), 차분하고 고급스러운
   - Color: 다크톤 배경(#0A0A0A ~ #1A1A1A) 기반, 포인트는 따뜻한 오렌지(#FF6B35 계열)
   - Typography: 산세리프, 큰 제목 + 넉넉한 행간, 흰색/밝은 회색 위주
   - Layout: 여백이 넉넉하고 미니멀. 과한 장식 금지.

2. Copy / Message tone
   - 간결, 담백, 정제된 표현. 과장·느낌표 남발 금지.
   - 미식·경험·취향을 중시하는 어휘 사용.
   - 사용자에게 반말/지나친 캐주얼 지양, 적절한 존칭.

3. Image / Photo 가이드
   - 고품질 음식/공간/사람 사진. 밝기·대비 과하지 않게.
   - 과도한 필터·강한 원색·만화적 일러스트 지양.
   - 로고는 원형 그대로 노출, 왜곡 금지.

4. Do / Don't
   - DO: 감각적인 식공간·테이블·디테일 클로즈업, 차분한 색감
   - DON'T: 클립아트, 싸구려 스톡 이미지, 혼잡한 타이포, 형광 색상
"""

# ---------------------------------------------------------------------------
# HTML (dark theme, per brand guide) — embedded
# ---------------------------------------------------------------------------
INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CatchTable · 브랜드 검수</title>
<style>
  :root{
    --bg:#0a0a0a;
    --bg-elev:#141414;
    --bg-elev-2:#1c1c1c;
    --border:#2a2a2a;
    --text:#ffffff;
    --text-dim:#9a9a9a;
    --text-faint:#6b6b6b;
    --accent:#ff6b35;
    --accent-dim:#ff8a5c;
    --ok:#36d399;
    --warn:#f6c453;
    --danger:#ef4444;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo",
      "Noto Sans KR",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;min-height:100vh}
  a{color:inherit}
  .wrap{max-width:880px;margin:0 auto;padding:56px 24px 120px}
  header{display:flex;align-items:baseline;gap:12px;margin-bottom:48px}
  .logo{font-size:20px;font-weight:700;letter-spacing:-.01em}
  .logo .dot{color:var(--accent)}
  .tag{font-size:12px;color:var(--text-faint);letter-spacing:.12em;text-transform:uppercase}
  h1{font-size:40px;line-height:1.15;letter-spacing:-.02em;font-weight:700;margin-bottom:12px}
  .sub{color:var(--text-dim);font-size:15px;margin-bottom:40px;line-height:1.6}

  .card{background:var(--bg-elev);border:1px solid var(--border);border-radius:14px;padding:28px;margin-bottom:20px}
  .label{font-size:12px;color:var(--text-faint);letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px}

  .drop{border:1.5px dashed #333;border-radius:12px;padding:44px 24px;text-align:center;
    background:var(--bg-elev-2);transition:border-color .15s, background .15s;cursor:pointer}
  .drop:hover,.drop.active{border-color:var(--accent);background:#1f1a18}
  .drop .icon{font-size:36px;margin-bottom:8px;display:block}
  .drop .title{font-size:15px;color:var(--text);margin-bottom:4px}
  .drop .hint{font-size:13px;color:var(--text-faint)}
  #fileInput{display:none}
  .btn-sec{display:inline-block;margin-top:14px;padding:10px 18px;border:1px solid #333;border-radius:8px;
    background:transparent;color:var(--text);font-size:13px;cursor:pointer;transition:border-color .15s}
  .btn-sec:hover{border-color:var(--accent)}
  .file-name{margin-top:12px;font-size:13px;color:var(--text-dim)}

  .preview{display:none;margin-top:18px;border-radius:10px;overflow:hidden;border:1px solid var(--border);background:#000}
  .preview.show{display:block}
  .preview img{display:block;width:100%;max-height:360px;object-fit:contain}

  .seg{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .seg button{background:var(--bg-elev-2);border:1px solid var(--border);color:var(--text-dim);
    padding:14px 12px;border-radius:10px;font-size:14px;cursor:pointer;transition:all .15s}
  .seg button:hover{color:var(--text);border-color:#3a3a3a}
  .seg button.on{background:#201713;color:var(--accent);border-color:var(--accent)}

  textarea{width:100%;min-height:72px;background:var(--bg-elev-2);border:1px solid var(--border);
    border-radius:10px;color:var(--text);padding:12px 14px;font-size:14px;line-height:1.5;resize:vertical;
    font-family:inherit}
  textarea:focus{outline:none;border-color:var(--accent)}
  textarea::placeholder{color:var(--text-faint)}

  .primary{display:flex;align-items:center;justify-content:center;gap:10px;
    width:100%;padding:18px;border:0;border-radius:12px;background:var(--accent);color:#fff;
    font-size:16px;font-weight:600;letter-spacing:-.005em;cursor:pointer;transition:background .15s;
    margin-top:4px}
  .primary:hover{background:var(--accent-dim)}
  .primary:disabled{background:#333;color:#777;cursor:not-allowed}
  .spinner{width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;
    border-radius:50%;animation:spin .7s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}

  .result{display:none}
  .result.show{display:block}
  .score-row{display:flex;align-items:center;gap:28px;padding:28px;background:var(--bg-elev);
    border:1px solid var(--border);border-radius:14px;margin-bottom:18px}
  .score-num{font-size:72px;line-height:1;font-weight:700;letter-spacing:-.03em}
  .score-meta{flex:1}
  .score-bar{height:6px;background:#222;border-radius:999px;overflow:hidden;margin-top:10px}
  .score-bar > span{display:block;height:100%;background:var(--accent);transition:width .6s ease}
  .score-label{font-size:13px;color:var(--text-dim);margin-top:8px}

  .section{padding:24px 28px;background:var(--bg-elev);border:1px solid var(--border);
    border-radius:14px;margin-bottom:14px}
  .section h3{font-size:13px;color:var(--text-faint);letter-spacing:.1em;text-transform:uppercase;
    margin-bottom:14px;font-weight:600}
  .section p, .section li{font-size:15px;line-height:1.7;color:var(--text)}
  .section ul{list-style:none;padding:0}
  .section li{padding:10px 0;border-bottom:1px solid var(--border)}
  .section li:last-child{border-bottom:0}
  .section li::before{content:"—";color:var(--accent);margin-right:10px}

  .meta-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:12px}
  .meta-grid .cell{background:var(--bg-elev-2);border:1px solid var(--border);
    border-radius:10px;padding:14px 16px}
  .meta-grid .cell .k{font-size:12px;color:var(--text-faint);margin-bottom:4px;letter-spacing:.06em;text-transform:uppercase}
  .meta-grid .cell .v{font-size:18px;font-weight:600}
  .meta-grid .cell .v.ok{color:var(--ok)} .meta-grid .cell .v.warn{color:var(--warn)} .meta-grid .cell .v.bad{color:var(--danger)}

  .footer{margin-top:40px;color:var(--text-faint);font-size:12px;text-align:center}
  .back{display:inline-block;margin-top:16px;padding:10px 18px;border:1px solid #333;border-radius:8px;
    background:transparent;color:var(--text-dim);font-size:13px;cursor:pointer}
  .back:hover{color:var(--text);border-color:var(--accent)}

  .banner{display:none;padding:12px 14px;border-radius:10px;background:#2a1f12;border:1px solid #4a3522;
    color:var(--warn);font-size:13px;margin-bottom:18px}
  .banner.show{display:block}

  @media (max-width:640px){
    .wrap{padding:32px 18px 80px}
    h1{font-size:30px}
    .score-row{flex-direction:column;align-items:flex-start;gap:14px}
    .score-num{font-size:56px}
    .seg{grid-template-columns:1fr 1fr 1fr}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">catch<span class="dot">·</span>table</div>
    <div class="tag">Brand Review</div>
  </header>

  <section class="input-phase">
    <h1>브랜드 검수</h1>
    <p class="sub">업로드한 이미지를 캐치테이블 브랜드 T&amp;M 가이드에 맞춰 AI가 자동으로 검수합니다.</p>

    <div id="banner" class="banner"></div>

    <div class="card">
      <div class="label">Image</div>
      <label for="fileInput" class="drop" id="dropZone">
        <span class="icon">⬆</span>
        <div class="title">이미지를 드래그하거나 클릭해 업로드</div>
        <div class="hint">PNG · JPG · WEBP · 최대 16MB</div>
        <span class="btn-sec">파일 선택</span>
        <div id="fileName" class="file-name"></div>
      </label>
      <input id="fileInput" type="file" accept="image/*">
      <div id="preview" class="preview"><img id="previewImg" alt=""></div>
    </div>

    <div class="card">
      <div class="label">Media</div>
      <div class="seg" id="seg">
        <button data-v="online" class="on">온라인</button>
        <button data-v="print">인쇄물</button>
        <button data-v="video">영상</button>
      </div>
    </div>

    <div class="card">
      <div class="label">Context <span style="color:var(--text-faint)">· optional</span></div>
      <textarea id="context" placeholder="예: 4월 미식 가이드 상세 페이지 메인 이미지"></textarea>
    </div>

    <button id="analyzeBtn" class="primary" disabled>
      <span id="btnText">이미지를 업로드해 주세요</span>
    </button>
  </section>

  <section id="resultPhase" class="result">
    <h1>검수 결과</h1>
    <p class="sub" id="resultSub">—</p>

    <div class="score-row">
      <div class="score-num" id="scoreNum">0</div>
      <div class="score-meta">
        <div class="label">Overall Score</div>
        <div class="score-bar"><span id="scoreBar" style="width:0%"></span></div>
        <div class="score-label" id="scoreLabel">—</div>
      </div>
    </div>

    <div class="section" id="summarySection">
      <h3>Summary</h3>
      <p id="summary">—</p>
      <div class="meta-grid" id="metaGrid"></div>
    </div>

    <div class="section" id="strengthsSection">
      <h3>Strengths</h3>
      <ul id="strengths"></ul>
    </div>

    <div class="section" id="improvementsSection">
      <h3>Improvements</h3>
      <ul id="improvements"></ul>
    </div>

    <button class="back" id="backBtn">← 다시 검수하기</button>
  </section>

  <div class="footer">© CatchTable · Brand Review Tool</div>
</div>

<script>
  const $ = (s) => document.querySelector(s);
  let selectedFile = null;
  let currentMedia = 'online';

  // Segmented control
  $('#seg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]'); if(!b) return;
    document.querySelectorAll('#seg button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); currentMedia = b.dataset.v;
  });

  // Drag & drop
  const dz = $('#dropZone');
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => {e.preventDefault(); dz.classList.add('active');}));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => {e.preventDefault(); dz.classList.remove('active');}));
  dz.addEventListener('drop', e => { if(e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); });
  $('#fileInput').addEventListener('change', e => { if(e.target.files[0]) handleFile(e.target.files[0]); });

  function handleFile(file){
    if (!file.type.startsWith('image/')){ showBanner('이미지 파일만 업로드할 수 있어요.'); return; }
    selectedFile = file;
    const r = new FileReader();
    r.onload = (e) => {
      $('#previewImg').src = e.target.result;
      $('#preview').classList.add('show');
    };
    r.readAsDataURL(file);
    $('#fileName').textContent = file.name;
    const btn = $('#analyzeBtn'); btn.disabled = false;
    $('#btnText').textContent = '검수 시작';
    hideBanner();
  }

  function showBanner(msg){ const b = $('#banner'); b.textContent = msg; b.classList.add('show'); }
  function hideBanner(){ $('#banner').classList.remove('show'); }

  $('#analyzeBtn').addEventListener('click', async () => {
    if(!selectedFile){ showBanner('이미지를 먼저 업로드해 주세요.'); return; }
    const btn = $('#analyzeBtn');
    btn.disabled = true;
    $('#btnText').innerHTML = '<span class="spinner"></span> 검수 중… (최대 60초)';

    const reader = new FileReader();
    reader.onload = async (e) => {
      try{
        const r = await fetch('/api/review', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            image: e.target.result,
            mediaType: currentMedia,
            context: $('#context').value || ''
          })
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || '요청 실패');
        render(data);
      } catch(err){
        showBanner('오류: ' + err.message);
        btn.disabled = false;
        $('#btnText').textContent = '다시 시도';
      }
    };
    reader.readAsDataURL(selectedFile);
  });

  function render(d){
    document.querySelector('.input-phase').style.display = 'none';
    $('#resultPhase').classList.add('show');

    const score = clamp(parseInt(d.overallScore ?? 0, 10), 0, 100);
    animateScore(score);
    $('#scoreBar').style.width = score + '%';
    $('#scoreLabel').textContent = scoreLabel(score) + (d.source === 'fallback' ? ' · (샘플 응답)' : '');
    $('#resultSub').textContent = d.summary || '—';
    $('#summary').textContent = d.summary || '—';

    const meta = d.subscores || {};
    const cells = [
      ['Visual · 색/톤', meta.tone],
      ['Typography', meta.typography],
      ['Composition', meta.composition],
      ['Brand Fit', meta.brandFit]
    ].filter(([,v]) => v != null);
    $('#metaGrid').innerHTML = cells.map(([k,v]) => {
      const cls = v >= 80 ? 'ok' : v >= 60 ? 'warn' : 'bad';
      return `<div class="cell"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`;
    }).join('') || '';

    fillList('#strengths', d.strengths || []);
    fillList('#improvements', d.improvements || []);
    window.scrollTo(0,0);
  }

  function animateScore(target){
    const el = $('#scoreNum'); let cur = 0;
    const step = Math.max(1, Math.ceil(target/30));
    const t = setInterval(() => {
      cur = Math.min(target, cur + step);
      el.textContent = cur;
      if (cur >= target) clearInterval(t);
    }, 20);
  }
  function scoreLabel(s){
    if (s >= 85) return '브랜드 가이드에 잘 부합합니다';
    if (s >= 70) return '일부 개선 여지가 있습니다';
    if (s >= 50) return '주요 개선 포인트가 있습니다';
    return '브랜드 가이드와 상당한 차이가 있습니다';
  }
  function clamp(n, a, b){ return Math.max(a, Math.min(b, n)); }
  function fillList(sel, arr){
    const el = document.querySelector(sel);
    if (!arr || !arr.length){ el.innerHTML = '<li>해당 없음</li>'; return; }
    el.innerHTML = arr.map(x => `<li>${escapeHtml(x)}</li>`).join('');
  }
  function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

  $('#backBtn').addEventListener('click', () => {
    document.querySelector('.input-phase').style.display = '';
    $('#resultPhase').classList.remove('show');
    $('#analyzeBtn').disabled = false;
    $('#btnText').textContent = '검수 시작';
    hideBanner();
  });
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------
REVIEW_PROMPT_TEMPLATE = """당신은 CatchTable 브랜드 시각 검수관입니다.
아래 [브랜드 가이드]를 기준으로, 업로드된 이미지를 검수하세요.

[브랜드 가이드]
{guide}

[매체 타입] {media_type}
[제작 맥락] {context}

반드시 아래 JSON 스키마에 맞춰 한국어로 응답하십시오. 다른 설명 문장은 절대 포함하지 마세요.
{{
  "overallScore": 0-100 사이 정수,
  "subscores": {{
    "tone": 0-100 정수,
    "typography": 0-100 정수,
    "composition": 0-100 정수,
    "brandFit": 0-100 정수
  }},
  "summary": "1~2문장 요약",
  "strengths": ["잘된 점 1", "잘된 점 2", "..."],
  "improvements": ["개선 포인트 1", "개선 포인트 2", "..."]
}}
"""


def build_prompt(media_type: str, context: str) -> str:
    return REVIEW_PROMPT_TEMPLATE.format(
        guide=BRAND_GUIDE.strip(),
        media_type=media_type or "online",
        context=(context or "없음").strip(),
    )


def parse_image(data_url: str):
    """Accept either a data URL or raw base64. Returns (mime, base64_str)."""
    if not data_url:
        raise ValueError("이미지 데이터가 비어있습니다.")
    m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.DOTALL)
    if m:
        return m.group(1), m.group(2)
    # raw base64 -> assume png
    return "image/png", data_url


def call_gemini(prompt: str, mime: str, b64: str) -> dict:
    """Call Gemini, trying models in order. Returns parsed JSON dict and the model used."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }

    errors = []
    for model in GEMINI_MODELS:
        url = GEMINI_URL_TEMPLATE.format(model=model, key=GEMINI_API_KEY)
        try:
            r = requests.post(url, json=payload, timeout=55)
        except requests.RequestException as exc:
            errors.append(f"{model}: network {exc}")
            log.warning("Gemini model=%s network error: %s", model, exc)
            continue

        log.info("Gemini model=%s status=%s bytes=%s", model, r.status_code, len(r.content))
        if r.status_code != 200:
            snippet = r.text[:200].replace("\n", " ")
            errors.append(f"{model}: {r.status_code} {snippet}")
            continue

        body = r.json()
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{model}: shape {exc}")
            continue

        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                errors.append(f"{model}: non-JSON response")
                continue
            parsed = json.loads(m.group(0))

        parsed.setdefault("modelUsed", model)
        return parsed

    raise RuntimeError("All models failed. " + " | ".join(errors))


def sample_response(reason: str = "") -> dict:
    return {
        "overallScore": 72,
        "subscores": {"tone": 70, "typography": 74, "composition": 75, "brandFit": 70},
        "summary": "샘플 응답입니다. 실제 Gemini 분석이 불가하여 기본 결과를 반환했습니다."
        + (f" (사유: {reason})" if reason else ""),
        "strengths": [
            "전반적인 구도는 안정적입니다.",
            "주요 피사체가 명확히 드러납니다.",
        ],
        "improvements": [
            "다크톤 배경 및 여백 확보로 브랜드 톤에 더 맞출 수 있습니다.",
            "타이포그래피의 위계(타이틀/서브)를 더 명확히 하면 좋습니다.",
            "포인트 컬러(오렌지) 사용을 최소화하여 절제된 무드 유지.",
        ],
        "source": "fallback",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(
        ok=True,
        geminiConfigured=bool(GEMINI_API_KEY),
        models=GEMINI_MODELS,
    )


@app.route("/debug/list-models", methods=["GET"])
def list_models():
    """Ask Google which models this API key can actually use."""
    if not GEMINI_API_KEY:
        return jsonify(error="GEMINI_API_KEY not set"), 400
    out = {}
    for api_version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={GEMINI_API_KEY}"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json().get("models", [])
                # Filter to multimodal-capable only
                mm = [
                    {
                        "name": m.get("name", "").replace("models/", ""),
                        "methods": m.get("supportedGenerationMethods", []),
                        "input": m.get("inputTokenLimit"),
                    }
                    for m in data
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                out[api_version] = {"count": len(mm), "models": mm[:40]}
            else:
                out[api_version] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as exc:  # noqa: BLE001
            out[api_version] = {"error": str(exc)}
    return jsonify(out)


@app.route("/api/review", methods=["POST"])
def review():
    try:
        data = request.get_json(silent=True) or {}
        image = data.get("image", "")
        media_type = data.get("mediaType", "online")
        context = data.get("context", "")

        if not image:
            return jsonify(error="이미지 데이터가 없습니다."), 400

        mime, b64 = parse_image(image)
        prompt = build_prompt(media_type, context)

        # Try real Gemini
        if GEMINI_API_KEY:
            try:
                result = call_gemini(prompt, mime, b64)
                # Attach source marker
                result.setdefault("source", "gemini")
                return jsonify(result)
            except Exception as exc:  # noqa: BLE001
                log.warning("Gemini failed, falling back to sample: %s", exc)
                return jsonify(sample_response(str(exc)[:120]))
        else:
            log.warning("GEMINI_API_KEY missing — returning sample")
            return jsonify(sample_response("GEMINI_API_KEY missing"))

    except Exception as exc:  # noqa: BLE001
        log.exception("review failed")
        return jsonify(error=f"서버 오류: {exc}"), 500


# ---------------------------------------------------------------------------
# Entry point (gunicorn uses app:app, local runs directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
