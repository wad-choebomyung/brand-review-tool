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
   - Typography: 산세리프 고딕, 큰 제목 + 넉넉한 행간, 흰색/밝은 회색 위주
   - Layout: 여백이 넉넉하고 미니멀. 과한 장식 금지.

2. Copy / Message tone
   - 간결, 담백, 정제된 표현. 과장·느낌표 남발 금지.
   - 미식·경험·취향을 중시하는 어휘 사용.
   - 사용자에게 반말/지나친 캐주얼 지양, 적절한 존칭.

3. Image / Photo 가이드
   - 고품질 음식/공간/사람 사진. 밝기·대비 과하지 않게.
   - 과도한 필터·강한 원색·만화적 일러스트 지양.
   - 로고는 원형 그대로 노출, 왜곡 금지.

4. 매체별 세부 규칙

[소셜콘텐츠 디자인]
- DO: 소구점이 큰 매장 이미지 위에 딥(어둡게) 처리하고, 가독성이 좋은 고딕 서체를 사용하여 구성한다.
- DON'T: 지면 내에 과도한 면분할을 주는 레이아웃을 지양한다.
- DON'T: 가독성이 약한 얇은 웨이트의 서체나 스크립트 서체는 사용하지 않는다.

[인앱 디자인]
- DO: 이미지와 텍스트는 자연스럽게 분리하여 서로 충돌하지 않도록 디자인한다.
- 이미지 위에 텍스트를 올릴 때는 충분한 대비와 여백을 확보한다.

[그래픽 디자인]
- DO: 장식과 요소가 많은 디자인은 지양하는 것을 원칙으로 한다.
- EXCEPTION: 콘텐츠 전달력과 마케팅 소구가 명확히 필요한 경우 예외적으로 적용 가능하며,
  이 경우 브랜드팀의 사전 검토가 필요하다.

5. 공통 Do / Don't
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
  header{display:flex;align-items:center;margin-bottom:48px}
  .logo{display:inline-flex;align-items:center;line-height:0}
  .logo svg{height:22px;width:auto;display:block}
  h1{font-size:40px;line-height:1.15;letter-spacing:-.02em;font-weight:700;margin-bottom:16px}
  .lede{color:var(--text);font-size:17px;font-weight:600;line-height:1.55;
    letter-spacing:-.005em;margin-bottom:12px}
  .sub{color:var(--text-dim);font-size:15px;margin-bottom:40px;line-height:1.7}

  .card{background:var(--bg-elev);border:1px solid var(--border);border-radius:14px;padding:28px;margin-bottom:20px}
  .label{font-size:12px;color:var(--text-faint);letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px}

  .drop{display:block;border:1.5px dashed #333;border-radius:12px;padding:44px 24px;text-align:center;
    background:var(--bg-elev-2);transition:border-color .15s, background .15s;cursor:pointer;position:relative}
  .drop:hover,.drop.active{border-color:var(--accent);background:#1f1a18}
  .drop .icon{font-size:36px;margin-bottom:10px;display:block;line-height:1}
  .drop .title{font-size:15px;color:var(--text);margin-bottom:4px;display:block}
  .drop .hint{font-size:13px;color:var(--text-faint);display:block}
  /* Robust visually-hidden pattern for file input */
  .sr-only{position:absolute!important;width:1px!important;height:1px!important;
    padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;
    white-space:nowrap!important;border:0!important;opacity:0!important;pointer-events:none!important}
  .btn-sec{display:inline-block;margin-top:14px;padding:10px 18px;border:1px solid #333;border-radius:8px;
    background:transparent;color:var(--text);font-size:13px;cursor:pointer;transition:border-color .15s}
  .drop:hover .btn-sec,.drop.active .btn-sec{border-color:var(--accent)}
  .file-name{margin-top:12px;font-size:13px;color:var(--text-dim);display:block;min-height:1em}

  .preview{display:none;margin-top:18px;border-radius:10px;overflow:hidden;border:1px solid var(--border);background:#000}
  .preview.show{display:block}
  .preview img{display:block;width:100%;max-height:360px;object-fit:contain}

  .seg{display:grid;gap:8px}
  .seg.cols-3{grid-template-columns:repeat(3,1fr)}
  .seg.cols-2{grid-template-columns:repeat(2,1fr)}
  .seg button{background:var(--bg-elev-2);border:1px solid var(--border);color:var(--text-dim);
    padding:14px 8px;border-radius:10px;font-size:13px;cursor:pointer;transition:all .15s;white-space:nowrap}
  .seg button:hover{color:var(--text);border-color:#3a3a3a}
  .seg button.on{background:#201713;color:var(--accent);border-color:var(--accent)}
  .subseg{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
  .subseg button{background:transparent;border:1px solid var(--border);color:var(--text-dim);
    padding:8px 14px;border-radius:999px;font-size:13px;cursor:pointer;transition:all .15s}
  .subseg button:hover{color:var(--text);border-color:#3a3a3a}
  .subseg button.on{background:#201713;color:var(--accent);border-color:var(--accent)}
  .cat-badge{display:inline-block;margin-left:10px;padding:3px 10px;border-radius:999px;
    background:#201713;border:1px solid var(--accent);color:var(--accent);
    font-size:11px;font-weight:500;letter-spacing:.04em;text-transform:none;vertical-align:middle}

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
  .result-thumb{display:none;margin-bottom:18px}
  .result-thumb.show{display:flex;align-items:center;gap:14px;padding:14px;background:var(--bg-elev);
    border:1px solid var(--border);border-radius:14px}
  .result-thumb img{width:96px;height:96px;object-fit:cover;border-radius:10px;flex-shrink:0;
    background:#000;border:1px solid var(--border)}
  .result-thumb .meta{min-width:0;flex:1}
  .result-thumb .meta .k{font-size:11px;color:var(--text-faint);letter-spacing:.08em;
    text-transform:uppercase;margin-bottom:4px}
  .result-thumb .meta .v{font-size:14px;color:var(--text);overflow:hidden;text-overflow:ellipsis;
    white-space:nowrap}
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
    .seg button{padding:12px 6px;font-size:12px}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo" aria-label="CatchTable">
      <svg viewBox="0 0 400 83" xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">
        <path d="M246.703 0V7.44169H231.034V45.4492H221.956V7.44169H206.293V0H246.703Z" fill="#FF6B35"/>
        <path d="M343.252 38.1971H364.038V45.4086H334.167V0H343.245V38.1971H343.252Z" fill="#FF6B35"/>
        <path d="M379.214 7.40784V18.7769H400V25.9884H379.214V38.0075H400V45.4153H370.129V0H400V7.40784H379.214Z" fill="#FF6B35"/>
        <path d="M240.984 45.4763L257.593 0H268.618L285.22 45.4763H275.493L263.041 9.41892L250.657 45.4763H240.991H240.984Z" fill="#FF6B35"/>
        <path d="M321.337 22.7449C323.074 22.0881 324.555 20.9844 325.785 19.427C327.428 17.3482 328.246 14.9646 328.246 12.2832C328.246 9.85906 327.651 7.72609 326.461 5.88429C325.271 4.04249 323.554 2.60697 321.303 1.56418C319.052 0.528167 316.396 0.0067749 313.327 0.0067749H293.805V45.483H313.327C316.396 45.483 319.052 44.9616 321.303 43.9256C323.554 42.8828 325.271 41.4473 326.461 39.6055C327.651 37.7637 328.246 35.6308 328.246 33.2066C328.246 30.5184 327.421 28.1417 325.785 26.0629C324.555 24.5122 323.074 23.4017 321.337 22.7449ZM302.89 7.40784H312.036C314.239 7.40784 315.963 7.92923 317.193 8.96525C318.424 10.008 319.046 11.4774 319.046 13.3802C319.046 15.2829 318.397 16.8538 317.099 17.9576C315.801 19.0613 314.05 19.6166 311.846 19.6166H302.897V7.40784H302.89ZM317.187 36.5246C315.956 37.5606 314.239 38.082 312.029 38.082H302.883V25.8665H311.833C314.037 25.8665 315.787 26.4217 317.085 27.5255C318.383 28.6292 319.032 30.1595 319.032 32.1029C319.032 34.0463 318.417 35.4818 317.18 36.5178L317.187 36.5246Z" fill="#FF6B35"/>
        <path d="M302.721 82.3529C288.208 82.3529 274.553 76.6853 264.278 66.3929L261.372 63.4812L267.185 57.6579L270.092 60.5696C278.812 69.3046 290.398 74.119 302.714 74.119C315.03 74.119 326.616 69.3046 335.336 60.5696L338.243 57.6579L344.057 63.4812L341.15 66.3929C330.875 76.6853 317.22 82.3529 302.707 82.3529H302.721Z" fill="#FF6B35"/>
        <path d="M2.86612 11.667C4.77913 8.20007 7.38838 5.49831 10.7006 3.5617C14.0129 1.63187 17.7105 0.663574 21.7798 0.663574C26.7482 0.663574 31.0069 1.84179 34.549 4.20498C38.0911 6.56818 40.6733 9.8929 42.2888 14.1927H37.0636C35.7927 11.1727 33.8459 8.80949 31.2367 7.10988C28.6274 5.41028 25.4706 4.55709 21.7798 4.55709C18.5081 4.55709 15.5676 5.32225 12.9584 6.85257C10.3491 8.38289 8.30094 10.5836 6.8138 13.4546C5.32666 16.3257 4.58309 19.6572 4.58309 23.4356C4.58309 27.214 5.32666 30.5387 6.8138 33.3894C8.30094 36.2402 10.3491 38.4273 12.9584 39.9576C15.5676 41.4879 18.5081 42.2531 21.7798 42.2531C25.4706 42.2531 28.6274 41.4135 31.2367 39.7342C33.8459 38.0549 35.7927 35.7255 37.0636 32.7461H42.2888C40.6733 36.9985 38.0843 40.2962 34.5219 42.6323C30.9528 44.9752 26.7077 46.1398 21.7866 46.1398C17.7105 46.1398 14.0197 45.1715 10.7074 43.2349C7.39514 41.2983 4.78589 38.6101 2.87288 35.1635C0.953121 31.7372 0 27.8234 0 23.4423C0 19.0613 0.953121 15.1407 2.86612 11.6738V11.667Z" fill="#FF6B35"/>
        <path d="M118.146 0.683899V4.45553H100.139V46.1534H95.5893V4.45553H77.5138V0.683899H118.146Z" fill="#FF6B35"/>
        <path d="M124.061 11.6805C125.974 8.21362 128.583 5.51863 131.896 3.58203C135.208 1.64542 138.899 0.677124 142.975 0.677124C147.943 0.677124 152.195 1.85534 155.737 4.21853C159.279 6.57495 161.862 9.90645 163.47 14.1995H158.252C156.981 11.1795 155.041 8.82304 152.425 7.12343C149.816 5.42383 146.666 4.57064 142.968 4.57064C139.696 4.57064 136.763 5.3358 134.147 6.86612C131.537 8.39644 129.489 10.5971 128.002 13.4682C126.515 16.3392 125.771 19.6639 125.771 23.4491C125.771 27.2343 126.515 30.5522 128.002 33.3962C129.489 36.2469 131.537 38.4341 134.147 39.9644C136.756 41.4947 139.696 42.2599 142.968 42.2599C146.659 42.2599 149.816 41.4202 152.425 39.7409C155.034 38.0616 156.974 35.7323 158.252 32.7597H163.47C161.855 37.0121 159.266 40.3097 155.704 42.6458C152.134 44.9819 147.896 46.1534 142.968 46.1534C138.892 46.1534 135.201 45.1851 131.889 43.2553C128.577 41.3187 125.967 38.6304 124.054 35.1838C122.141 31.7372 121.188 27.8302 121.188 23.4491C121.188 19.0681 122.141 15.1475 124.054 11.6805H124.061Z" fill="#FF6B35"/>
        <path d="M200.23 0.650024V46.1534H195.681V24.8779H171.068V46.1534H166.519V0.650024H171.068V21.1062H195.681V0.650024H200.23Z" fill="#FF6B35"/>
        <path d="M45.4524 46.1534L62.6627 0.663574H67.8609L85.0711 46.1534H80.1365L65.2652 5.62696L50.2653 46.1534H45.4592H45.4524Z" fill="#FF6B35"/>
      </svg>
    </div>
  </header>

  <section class="input-phase">
    <h1>브랜드 톤앤매너 검수</h1>
    <p class="lede">업로드한 디자인 산출물을 기반으로, 캐치테이블의 브랜드 아이덴티티와 디자인 시스템 전반에 대한 적합성을 AI가 자동으로 분석·검수합니다.</p>
    <p class="sub">컬러, 타이포그래피, 그래픽 스타일, 컴포넌트 사용 방식 등 핵심 브랜드 자산이 가이드라인에 맞게 일관되게 적용되었는지 점검하며, 브랜드 톤앤매너와의 정합성을 종합적으로 평가합니다. 이를 통해 개별 디자이너의 해석에 의존하지 않고, 조직 전반에서 동일한 기준으로 브랜드 품질을 유지할 수 있도록 지원합니다.</p>

    <div id="banner" class="banner"></div>

    <div class="card">
      <div class="label">Image</div>
      <label class="drop" id="dropZone">
        <input id="fileInput" type="file" accept="image/*" class="sr-only">
        <span class="icon">⬆</span>
        <span class="title">이미지를 드래그하거나 클릭해 업로드</span>
        <span class="hint">PNG · JPG · WEBP · 최대 16MB</span>
        <span class="btn-sec">파일 선택</span>
        <span id="fileName" class="file-name"></span>
      </label>
      <div id="preview" class="preview"><img id="previewImg" alt=""></div>
    </div>

    <div class="card">
      <div class="label">Media</div>
      <div class="seg cols-3" id="seg">
        <button data-v="social" class="on">소셜콘텐츠</button>
        <button data-v="inapp">인앱</button>
        <button data-v="print">인쇄물</button>
      </div>
      <div class="subseg" id="subseg"></div>
    </div>

    <div class="card">
      <div class="label">추가 검수 기준 <span style="color:var(--text-faint)">· 복수 선택 가능</span></div>
      <div class="seg cols-2" id="segAlt">
        <button data-v="graphic">그래픽 검수</button>
        <button data-v="tone">이미지 톤앤매너</button>
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

    <div id="resultThumb" class="result-thumb">
      <img id="resultThumbImg" alt="업로드한 이미지">
      <div class="meta">
        <div class="k">Reviewed Image</div>
        <div class="v" id="resultThumbName">—</div>
      </div>
    </div>

    <div class="score-row">
      <div class="score-num" id="scoreNum">0</div>
      <div class="score-meta">
        <div class="label">Overall Score</div>
        <div class="score-bar"><span id="scoreBar" style="width:0%"></span></div>
        <div class="score-label" id="scoreLabel">—</div>
      </div>
    </div>

    <div class="section" id="summarySection">
      <h3>Summary <span id="categoryBadge" class="cat-badge" style="display:none"></span></h3>
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

  <div class="footer">© CatchTable · 브랜드 톤앤매너 검수</div>
</div>

<script>
  const $ = (s) => document.querySelector(s);
  let selectedFile = null;
  let selectedDataUrl = null;
  let currentMedia = 'social';
  let currentSubtype = '';
  let extraChecks = [];

  const SUBTYPES = {
    social: [['feed','정방형 피드'],['reels','릴스 커버'],['ext-feature','외부용 기획전']],
    inapp:  [['home','메인 배너'],['feature','기획전'],['intro','인트로 팝업'],['og','OG']],
    print:  [['poster','매장 부착용 포스터'],['brochure','브로슈어']]
  };

  function renderSubtypes(media){
    const wrap = $('#subseg');
    const list = SUBTYPES[media] || [];
    wrap.innerHTML = list.map(([v,l]) => `<button data-sv="${v}">${l}</button>`).join('');
    currentSubtype = '';
  }

  // Primary Media: one-of social/inapp/print (always exactly one selected)
  $('#seg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]'); if(!b) return;
    document.querySelectorAll('#seg button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); currentMedia = b.dataset.v;
    renderSubtypes(currentMedia);
  });

  // Additional criteria: multi-select toggles (graphic / tone)
  $('#segAlt').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]'); if(!b) return;
    b.classList.toggle('on');
    const v = b.dataset.v;
    if (b.classList.contains('on')) {
      if (!extraChecks.includes(v)) extraChecks.push(v);
    } else {
      extraChecks = extraChecks.filter(x => x !== v);
    }
  });

  // Subtype chips (within Media)
  $('#subseg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-sv]'); if(!b) return;
    const wasOn = b.classList.contains('on');
    document.querySelectorAll('#subseg button').forEach(x => x.classList.remove('on'));
    if (!wasOn){ b.classList.add('on'); currentSubtype = b.dataset.sv; }
    else { currentSubtype = ''; }
  });

  renderSubtypes(currentMedia);

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
      selectedDataUrl = e.target.result;
      $('#previewImg').src = selectedDataUrl;
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

    const sendReview = async (dataUrl) => {
      try{
        const r = await fetch('/api/review', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            image: dataUrl,
            mediaType: currentMedia,
            subtype: currentSubtype,
            extras: extraChecks,
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

    if (selectedDataUrl) {
      sendReview(selectedDataUrl);
    } else {
      const reader = new FileReader();
      reader.onload = (e) => { selectedDataUrl = e.target.result; sendReview(selectedDataUrl); };
      reader.readAsDataURL(selectedFile);
    }
  });

  function render(d){
    document.querySelector('.input-phase').style.display = 'none';
    $('#resultPhase').classList.add('show');

    if (selectedDataUrl) {
      $('#resultThumbImg').src = selectedDataUrl;
      $('#resultThumbName').textContent = (selectedFile && selectedFile.name) || '업로드한 이미지';
      $('#resultThumb').classList.add('show');
    }

    const score = clamp(parseInt(d.overallScore ?? 0, 10), 0, 100);
    animateScore(score);
    $('#scoreBar').style.width = score + '%';
    $('#scoreLabel').textContent = scoreLabel(score) + (d.source === 'fallback' ? ' · (샘플 응답)' : '');
    $('#resultSub').textContent = d.summary || '—';
    $('#summary').textContent = d.summary || '—';

    const CATEGORY_KO = {
      food:'음식', space:'공간', people:'인물',
      logo:'로고', event:'이벤트', graphic:'그래픽', other:'기타'
    };
    const badge = $('#categoryBadge');
    if (d.category) {
      badge.textContent = CATEGORY_KO[d.category] || d.category;
      badge.style.display = 'inline-block';
    } else {
      badge.style.display = 'none';
    }

    const meta = d.subscores || {};
    const cells = [
      ['Tone · 색/톤', meta.tone],
      ['Typography', meta.typography],
      ['Composition', meta.composition],
      ['Image Quality', meta.imageQuality],
      ['Text · Image Harmony', meta.textImageHarmony],
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
    $('#resultThumb').classList.remove('show');
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
MEDIA_LABELS = {
    "social":  "소셜콘텐츠 디자인",
    "inapp":   "인앱 디자인",
    "print":   "인쇄물",
    "graphic": "그래픽 검수",
    "tone":    "이미지 톤앤매너",
}

SUBTYPE_LABELS = {
    # social
    "feed": "정방형 피드", "reels": "릴스 커버", "ext-feature": "외부용 기획전",
    # inapp
    "home": "메인 배너", "feature": "기획전", "intro": "인트로 팝업", "og": "OG",
    # print
    "poster": "매장 부착용 포스터", "brochure": "브로슈어",
}

CATEGORY_HINTS = {
    "social":  ("소셜콘텐츠는 '소구점이 큰 매장 이미지 위 딥(어둡게) 처리 + 가독성 좋은 고딕' 원칙을 핵심 기준으로 삼는다. "
                "과도한 면분할 레이아웃, 얇은 웨이트 서체/스크립트 서체는 감점 사유다."),
    "inapp":   ("인앱은 '이미지와 텍스트가 자연스럽게 분리되어 충돌하지 않는가'가 핵심이다. "
                "텍스트 영역과 이미지 영역의 대비·여백이 충분한지, 앱 UI로서 가독성이 확보되는지 평가한다."),
    "print":   "인쇄물은 인쇄 환경(여백·대비·글자 크기)과 브랜드 톤 일관성을 함께 본다.",
    "graphic": ("그래픽 검수는 장식·요소 과다 여부, 콘텐츠 전달력·마케팅 소구의 명확성, "
                "예외 적용 근거의 타당성을 집중적으로 평가한다. 기본은 심플 원칙."),
    "tone":    ("이미지 톤앤매너 검수는 이미지 자체의 색감·노출·질감·연출·무드가 "
                "캐치테이블 브랜드 기준(세련·미식·차분한 고급감)과 부합하는지 집중 평가한다. "
                "레이아웃/카피는 부차적이며 순수 이미지의 톤을 1순위로 본다."),
}

EXTRA_KEYS = ("graphic", "tone")

REVIEW_PROMPT_TEMPLATE = """당신은 CatchTable 브랜드 시각 검수관입니다.
아래 [브랜드 가이드]를 기준으로, 업로드된 이미지를 검수하세요.

[브랜드 가이드]
{guide}

[매체 타입] {media_label} (key={media_type})
[세부 타입] {subtype_label}
[이 매체의 핵심 기준] {category_hint}
[추가 검수 기준]
{extras_block}
[제작 맥락] {context}

먼저 이미지의 콘텐츠 카테고리를 아래 중 하나로 판정하고,
매체 타입 기준과 추가 검수 기준을 모두 반영해 점수를 매기세요.
추가 기준이 여러 개면 각 기준의 관점을 summary/strengths/improvements에 균형 있게 반영합니다.
  - food(음식), space(공간·매장), people(인물), logo(로고),
    event(이벤트 배너/쿠폰), graphic(그래픽/일러스트), other(기타)

반드시 아래 JSON 스키마에 맞춰 한국어로만 응답하십시오. 다른 설명 문장은 절대 포함하지 마세요.
{{
  "category": "food|space|people|logo|event|graphic|other 중 하나",
  "overallScore": 0-100 사이 정수,
  "subscores": {{
    "tone": 0-100 정수,
    "typography": 0-100 정수,
    "composition": 0-100 정수,
    "imageQuality": 0-100 정수,
    "textImageHarmony": 0-100 정수,
    "brandFit": 0-100 정수
  }},
  "summary": "1~2문장 요약 (매체 타입과 카테고리에 맞춘 총평)",
  "strengths": ["잘된 점 1", "잘된 점 2", "..."],
  "improvements": ["개선 포인트 1", "개선 포인트 2", "..."]
}}
"""


def build_prompt(media_type: str, subtype: str, extras, context: str) -> str:
    mt = media_type or "social"
    extras = [e for e in (extras or []) if e in EXTRA_KEYS]
    if extras:
        lines = [
            f"- {MEDIA_LABELS.get(e, e)}: {CATEGORY_HINTS.get(e, '')}"
            for e in extras
        ]
        extras_block = "\n".join(lines)
    else:
        extras_block = "(없음)"
    return REVIEW_PROMPT_TEMPLATE.format(
        guide=BRAND_GUIDE.strip(),
        media_type=mt,
        media_label=MEDIA_LABELS.get(mt, mt),
        subtype_label=SUBTYPE_LABELS.get(subtype or "", "지정되지 않음"),
        category_hint=CATEGORY_HINTS.get(mt, ""),
        extras_block=extras_block,
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


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "category": {"type": "STRING"},
        "overallScore": {"type": "INTEGER"},
        "subscores": {
            "type": "OBJECT",
            "properties": {
                "tone": {"type": "INTEGER"},
                "typography": {"type": "INTEGER"},
                "composition": {"type": "INTEGER"},
                "imageQuality": {"type": "INTEGER"},
                "textImageHarmony": {"type": "INTEGER"},
                "brandFit": {"type": "INTEGER"},
            },
            "required": ["tone", "typography", "composition",
                         "imageQuality", "textImageHarmony", "brandFit"],
        },
        "summary": {"type": "STRING"},
        "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
        "improvements": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["category", "overallScore", "subscores",
                 "summary", "strengths", "improvements"],
}


def _clean_json_text(text: str) -> str:
    """Strip code fences, pull out the outermost JSON object, repair common issues."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Outermost {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    # Strip //-comments and /* */ blocks (Gemini sometimes adds them)
    text = re.sub(r"//[^\n\r]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


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
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
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
            finish = (body.get("candidates", [{}])[0] or {}).get("finishReason", "?")
            errors.append(f"{model}: shape {exc} (finish={finish})")
            continue

        cleaned = _clean_json_text(text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            snippet = cleaned[:240].replace("\n", " ")
            log.warning("Gemini model=%s JSON parse failed: %s :: %s", model, exc, snippet)
            errors.append(f"{model}: JSON {exc.msg} @ line{exc.lineno} col{exc.colno}")
            continue

        parsed.setdefault("modelUsed", model)
        return parsed

    raise RuntimeError("All models failed. " + " | ".join(errors))


def sample_response(reason: str = "") -> dict:
    return {
        "category": "graphic",
        "overallScore": 72,
        "subscores": {
            "tone": 70,
            "typography": 74,
            "composition": 75,
            "imageQuality": 76,
            "textImageHarmony": 72,
            "brandFit": 70,
        },
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
        media_type = data.get("mediaType", "social")
        subtype = data.get("subtype", "")
        extras = data.get("extras", []) or []
        context = data.get("context", "")

        if not image:
            return jsonify(error="이미지 데이터가 없습니다."), 400

        mime, b64 = parse_image(image)
        prompt = build_prompt(media_type, subtype, extras, context)

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
