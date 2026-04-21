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
import time
import uuid
import secrets
import logging
import threading
from collections import deque, defaultdict
from functools import wraps
import requests
from flask import Flask, request, jsonify, Response, session, redirect, url_for

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB (base64 오버헤드 고려)
# SECRET_KEY 는 세션 쿠키 서명용. 환경변수로 받고, 없으면 기동마다 랜덤 생성(=재배포 시 재로그인).
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "1") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("brand-review")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN", "").strip()
# 렌더 스케일: 너무 크면 base64 전송비 증가, 너무 작으면 품질 저하. 1.5 권장.
FIGMA_RENDER_SCALE = os.environ.get("FIGMA_RENDER_SCALE", "1.5")

# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-session)
#   - REVIEW_RATE_MIN:  회/분  (기본 5)
#   - REVIEW_RATE_HOUR: 회/시간 (기본 30)
# 여러 gunicorn 워커가 있으면 각 워커 별로 카운트 (대략치). 악용 방지 수준으로 충분.
# ---------------------------------------------------------------------------
REVIEW_RATE_MIN = int(os.environ.get("REVIEW_RATE_MIN", "5"))
REVIEW_RATE_HOUR = int(os.environ.get("REVIEW_RATE_HOUR", "30"))
_rl_lock = threading.Lock()
_rl_hits = defaultdict(deque)  # key -> deque[timestamp]

def _rate_limit_check(key: str):
    now = time.time()
    with _rl_lock:
        dq = _rl_hits[key]
        while dq and now - dq[0] > 3600:
            dq.popleft()
        last_min = sum(1 for t in dq if now - t <= 60)
        if last_min >= REVIEW_RATE_MIN:
            return False, "분당 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        if len(dq) >= REVIEW_RATE_HOUR:
            return False, "시간당 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        dq.append(now)
    return True, ""
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
<meta name="theme-color" content="#0a0a0a">
<meta name="robots" content="noindex,nofollow">
<title>CatchTable · 브랜드 톤앤매너 검수</title>
<style>
  :root{
    --bg:#0a0a0a;
    --bg-elev:#141414;
    --bg-elev-2:#1c1c1c;
    --border:#2a2a2a;
    --text:#ffffff;
    --text-dim:#a4a4a4;
    --text-faint:#8a8a8a;
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
  header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:48px}
  .logo{display:inline-flex;align-items:center;line-height:0}
  .logo svg{height:22px;width:auto;display:block}
  .gnb{display:inline-flex;gap:8px}
  .gnb a{display:inline-flex;align-items:center;gap:6px;padding:9px 14px;background:var(--bg-elev-2);border:1px solid var(--border);color:var(--text-dim);border-radius:10px;font-size:13px;text-decoration:none;transition:all .15s;white-space:nowrap;font-weight:500}
  .gnb a:hover{color:var(--text);border-color:#3a3a3a}
  .gnb a.on{background:#201713;color:var(--accent);border-color:var(--accent)}
  .gnb svg{width:14px;height:14px;flex-shrink:0;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  /* mode-based show/hide */
  .figma-input{display:none}
  body[data-mode="figma"] .image-input{display:none}
  body[data-mode="figma"] .figma-input{display:block}
  body[data-mode="figma"] h1.page-title::after{content:" · Figma"}
  /* Figma URL input */
  .url-input{width:100%;margin-top:12px;padding:14px 16px;background:var(--bg-elev);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:14px;font-family:inherit;transition:border-color .15s}
  .url-input:focus{border-color:var(--accent)}
  .figma-preview{margin-top:12px;padding:12px 14px;background:var(--bg-elev);border:1px solid var(--border);border-radius:10px;font-size:13px;color:var(--text-dim);display:none}
  .figma-preview.show{display:flex;align-items:center;gap:10px}
  .figma-preview .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex-shrink:0}
  .figma-preview.loading .dot{background:var(--warn);animation:pulse 1s ease-in-out infinite}
  .figma-preview.error .dot{background:var(--danger)}
  @keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
  @media (max-width:640px){
    header{margin-bottom:32px}
    .gnb a{padding:8px 10px;font-size:12px}
  }
  h1{font-size:56px;line-height:1.1;letter-spacing:-.03em;font-weight:800;margin-bottom:24px}
  .lede{color:var(--text-dim);font-size:17px;font-weight:400;line-height:1.65;
    letter-spacing:-.005em;margin-bottom:36px;max-width:760px}
  .sub{color:var(--text-dim);font-size:15px;margin-bottom:40px;line-height:1.7}

  .divider{height:1px;background:var(--border);margin:0 0 36px}
  .features{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin-bottom:56px}
  .feature{display:flex;gap:14px;align-items:flex-start}
  .feature .icon-wrap{width:48px;height:48px;flex-shrink:0;background:var(--bg-elev);
    border:1px solid var(--border);border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--accent)}
  .feature .icon-wrap svg{width:24px;height:24px;display:block}
  .feature .f-body{min-width:0}
  .feature h4{font-size:14px;font-weight:700;margin-bottom:6px;color:var(--text);letter-spacing:-.005em}
  .feature p{font-size:13px;color:var(--text-dim);line-height:1.6}

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
    margin-top:4px;position:relative;overflow:hidden;isolation:isolate}
  .primary:hover{background:var(--accent-dim)}
  .primary:disabled{background:#333;color:#777;cursor:not-allowed}
  .primary::before{content:"";position:absolute;top:0;left:0;bottom:0;width:0;
    background:linear-gradient(90deg, rgba(255,107,53,.55), rgba(255,107,53,.38));
    z-index:-1;pointer-events:none;border-radius:inherit}
  .primary.loading::before{width:96%;
    transition:width var(--progress-dur,60s) cubic-bezier(.08,.7,.35,1)}
  .primary.loading::after{content:"";position:absolute;inset:0;
    background:linear-gradient(90deg, transparent 0%, rgba(255,255,255,.18) 50%, transparent 100%);
    background-size:35% 100%;background-repeat:no-repeat;background-position:-35% 0;
    animation:shimmer 1.8s ease-in-out infinite;z-index:-1;pointer-events:none;border-radius:inherit}
  @keyframes shimmer{
    0%{background-position:-35% 0}
    100%{background-position:135% 0}
  }
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
    border:1px solid var(--border);border-radius:14px;margin-bottom:4px}
  .score-meta{flex:1}
  .score-meta .label{margin-bottom:2px}
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
  .banner.error{background:#2a1515;border-color:#5a2626;color:#ff8a8a}

  /* Keyboard focus */
  *:focus{outline:none}
  *:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
  .primary:focus-visible, .seg button:focus-visible, .subseg button:focus-visible,
  .back:focus-visible, .btn-sec:focus-visible, .toolbtn:focus-visible{outline-offset:3px}

  /* Score ring */
  .ring-wrap{position:relative;width:128px;height:128px;flex-shrink:0}
  .ring-wrap svg{transform:rotate(-90deg);display:block}
  .ring-wrap .ring-bg{stroke:#222;fill:none}
  .ring-wrap .ring-fg{stroke:var(--accent);fill:none;stroke-linecap:round;
    transition:stroke-dashoffset .8s cubic-bezier(.2,.7,.3,1)}
  .ring-wrap .ring-num{position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;font-size:36px;font-weight:700;letter-spacing:-.02em}

  /* Result toolbar */
  .toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 22px}
  .toolbtn{display:inline-flex;align-items:center;gap:6px;padding:10px 14px;
    background:var(--bg-elev);border:1px solid var(--border);border-radius:10px;
    color:var(--text-dim);font-size:13px;cursor:pointer;transition:all .15s;
    font-family:inherit}
  .toolbtn:hover{color:var(--text);border-color:#3a3a3a}
  .toolbtn.on{color:var(--accent);border-color:var(--accent)}
  .toolbtn svg{width:14px;height:14px}

  @media (max-width:640px){
    .wrap{padding:32px 18px 80px}
    h1{font-size:36px}
    .lede{font-size:15px;margin-bottom:28px}
    .features{grid-template-columns:1fr;gap:20px;margin-bottom:40px}
    .score-row{flex-direction:column;align-items:flex-start;gap:14px}
    .ring-wrap{width:108px;height:108px}
    .ring-wrap svg{width:108px;height:108px}
    .ring-wrap .ring-num{font-size:30px}
    .seg button{padding:12px 6px;font-size:12px;min-height:44px}
    .toolbar{gap:6px}
    .toolbtn{padding:9px 10px;font-size:12px}
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
    <nav class="gnb" aria-label="검수 방식 선택">
      <a href="/" data-page="image">
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
        이미지 검수
      </a>
      <a href="/figma" data-page="figma">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 2h3v6H9a3 3 0 1 1 0-6z"/><path d="M12 2h3a3 3 0 1 1 0 6h-3V2z"/><path d="M9 8h3v6H9a3 3 0 1 1 0-6z"/><path d="M12 8h3a3 3 0 1 1-3 3V8z" fill="none"/><circle cx="15" cy="11" r="3"/><path d="M9 14h3v3a3 3 0 1 1-3-3z"/></svg>
        Figma 검수
      </a>
    </nav>
  </header>

  <section class="input-phase">
    <h1>브랜드 톤앤매너 검수</h1>
    <p class="lede">업로드한 디자인 산출물을 기반으로, 캐치테이블의 브랜드 아이덴티티와 디자인 시스템 전반에 대한 적합성을 AI가 자동으로 분석·검수합니다.</p>

    <div class="divider"></div>

    <div class="features">
      <div class="feature">
        <div class="icon-wrap" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="17.5" cy="15.5" r="1.5"/><circle cx="13.5" cy="19.5" r="1.5"/><path d="M12 2a10 10 0 1 0 0 20c1.1 0 2-.9 2-2a2 2 0 0 1 2-2h2a4 4 0 0 0 4-4 10 10 0 0 0-10-10z"/></svg>
        </div>
        <div class="f-body">
          <h4>핵심 자산 검수</h4>
          <p>컬러, 타이포그래피, 그래픽 스타일, 컴포넌트 사용 방식 등 핵심 브랜드 자산이 가이드라인에 맞게 적용되었는지 점검합니다.</p>
        </div>
      </div>
      <div class="feature">
        <div class="icon-wrap" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>
        </div>
        <div class="f-body">
          <h4>일관성 및 정합성 평가</h4>
          <p>브랜드 톤앤매너와의 정합성을 종합적으로 평가하여 디자인의 일관성과 완성도를 높입니다.</p>
        </div>
      </div>
      <div class="feature">
        <div class="icon-wrap" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.5 4.5 5.5v5.5c0 4.7 3.2 8.8 7.5 10.5 4.3-1.7 7.5-5.8 7.5-10.5V5.5L12 2.5z"/><path d="m8.8 12.2 2.4 2.4 4.2-4.6"/></svg>
        </div>
        <div class="f-body">
          <h4>브랜드 품질 유지 지원</h4>
          <p>조직 전반에서 동일한 기준으로 브랜드 품질을 유지할 수 있도록 체계적으로 지원합니다.</p>
        </div>
      </div>
    </div>

    <div id="banner" class="banner" role="alert" aria-live="polite"></div>

    <div class="card image-input">
      <div class="label">이미지</div>
      <label class="drop" id="dropZone">
        <input id="fileInput" type="file" accept="image/*" class="sr-only">
        <span class="icon">⬆</span>
        <span class="title">이미지를 드래그하거나 클릭해 업로드</span>
        <span class="hint">PNG · JPG · WEBP · 자동 최적화 (긴 변 2048px)</span>
        <span class="btn-sec">파일 선택</span>
        <span id="fileName" class="file-name"></span>
      </label>
      <div id="preview" class="preview"><img id="previewImg" alt=""></div>
    </div>

    <div class="card figma-input">
      <div class="label">Figma 링크</div>
      <label class="drop" id="figmaDropZone" for="figmaUrlInput">
        <span class="icon">⧉</span>
        <span class="title">Figma URL을 여기에 드래그하거나 아래에 붙여넣기</span>
        <span class="hint">특정 프레임을 선택한 상태로 복사한 URL이 필요해요 (node-id 포함)</span>
        <span class="btn-sec">URL 붙여넣기</span>
      </label>
      <input id="figmaUrlInput" class="url-input" type="url" autocomplete="off" spellcheck="false"
             placeholder="https://www.figma.com/design/XXXX/파일명?node-id=12-345">
      <div id="figmaPreview" class="figma-preview" role="status" aria-live="polite">
        <span class="dot"></span>
        <span id="figmaPreviewText">—</span>
      </div>
    </div>

    <div class="card">
      <div class="label">매체 타입</div>
      <div class="seg cols-3" id="seg" role="radiogroup" aria-label="매체 타입">
        <button data-v="social" class="on" role="radio" aria-checked="true">소셜콘텐츠</button>
        <button data-v="inapp" role="radio" aria-checked="false">인앱</button>
        <button data-v="print" role="radio" aria-checked="false">인쇄물</button>
      </div>
      <div class="subseg" id="subseg"></div>
    </div>

    <div class="card">
      <div class="label">추가 검수 기준 <span style="color:var(--text-faint)">· 복수 선택 가능</span></div>
      <div class="seg cols-2" id="segAlt">
        <button data-v="graphic" aria-pressed="false">그래픽 검수</button>
        <button data-v="tone" aria-pressed="false">이미지 톤앤매너</button>
      </div>
    </div>

    <div class="card">
      <div class="label">제작 맥락 <span style="color:var(--text-faint)">· 선택</span></div>
      <textarea id="context" placeholder="예: 4월 미식 가이드 상세 페이지 메인 이미지"></textarea>
    </div>

    <button id="analyzeBtn" class="primary" disabled>
      <span id="btnText">이미지를 업로드해 주세요</span>
    </button>
  </section>

  <section id="resultPhase" class="result" aria-live="polite">
    <h1>검수 결과</h1>
    <p class="sub" id="resultSub">—</p>

    <div id="resultThumb" class="result-thumb">
      <img id="resultThumbImg" alt="검수한 업로드 이미지">
      <div class="meta">
        <div class="k">검수 이미지</div>
        <div class="v" id="resultThumbName">—</div>
      </div>
    </div>

    <div class="score-row">
      <div class="ring-wrap" aria-label="종합 점수">
        <svg width="128" height="128" viewBox="0 0 128 128" aria-hidden="true">
          <circle class="ring-bg" cx="64" cy="64" r="56" stroke-width="10"/>
          <circle id="scoreRing" class="ring-fg" cx="64" cy="64" r="56" stroke-width="10"
                  stroke-dasharray="351.86" stroke-dashoffset="351.86"/>
        </svg>
        <div class="ring-num" id="scoreNum">0</div>
      </div>
      <div class="score-meta">
        <div class="label">종합 점수</div>
        <div class="score-label" id="scoreLabel">—</div>
      </div>
    </div>

    <div class="toolbar" role="toolbar" aria-label="결과 공유 도구">
      <button class="toolbtn" id="btnReanalyze" title="같은 이미지로 매체 타입만 바꿔서 다시 검수">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/><path d="M3 21v-5h5"/></svg>
        매체 바꿔 재검수
      </button>
      <button class="toolbtn" id="btnCopy">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
        텍스트 복사
      </button>
      <button class="toolbtn" id="btnDownload">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v14"/><path d="m6 11 6 6 6-6"/><path d="M4 21h16"/></svg>
        이미지 저장
      </button>
      <button class="toolbtn" id="btnShareUrl">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>
        공유 링크 복사
      </button>
    </div>

    <div id="captureArea">
      <div class="section" id="summarySection">
        <h3>요약 <span id="categoryBadge" class="cat-badge" style="display:none"></span></h3>
        <p id="summary">—</p>
        <div class="meta-grid" id="metaGrid"></div>
      </div>

      <div class="section" id="strengthsSection">
        <h3>강점</h3>
        <ul id="strengths"></ul>
      </div>

      <div class="section" id="improvementsSection">
        <h3>개선점</h3>
        <ul id="improvements"></ul>
      </div>
    </div>

    <button class="back" id="backBtn">← 새 이미지로 검수하기</button>
  </section>

  <div class="footer">
    © CatchTable · 브랜드 톤앤매너 검수
    <form method="post" action="/logout" class="logout-form" style="display:inline;margin-left:10px">
      <button type="submit" style="background:none;border:0;color:inherit;font-size:12px;cursor:pointer;padding:0;text-decoration:underline">로그아웃</button>
    </form>
  </div>
</div>

<script>
  const $ = (s) => document.querySelector(s);
  let selectedFile = null;
  let selectedDataUrl = null;
  let currentMedia = 'social';
  let currentSubtype = '';
  let extraChecks = [];
  // Figma mode state
  const PAGE_MODE = document.body.dataset.mode === 'figma' ? 'figma' : 'image';
  let figmaUrlOk = false;   // 현재 입력된 URL이 유효한지
  let figmaParsedUrl = '';  // 유효 URL 원문 (서버에 보낼 값)
  let figmaFrameName = '';  // 검수 결과에 표시할 식별자

  // GNB 현재 모드 활성화
  document.querySelectorAll('.gnb a[data-page]').forEach(a => {
    a.classList.toggle('on', a.dataset.page === PAGE_MODE);
  });

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
    document.querySelectorAll('#seg button').forEach(x => {
      x.classList.remove('on'); x.setAttribute('aria-checked', 'false');
    });
    b.classList.add('on'); b.setAttribute('aria-checked', 'true');
    currentMedia = b.dataset.v;
    renderSubtypes(currentMedia);
  });

  // Additional criteria: multi-select toggles (graphic / tone)
  $('#segAlt').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]'); if(!b) return;
    b.classList.toggle('on');
    const on = b.classList.contains('on');
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    const v = b.dataset.v;
    if (on) {
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

  // 업로드 이미지를 긴 변 MAX_EDGE 이하로 리사이즈하고 JPEG 0.85로 재인코딩
  // (GIF 등은 원본 유지)
  function downscaleImage(file, maxEdge = 2048, quality = 0.85){
    return new Promise((resolve, reject) => {
      if (!file.type.startsWith('image/')) return reject(new Error('이미지 파일만 업로드할 수 있어요.'));
      const keepOriginal = (file.type === 'image/gif' || file.type === 'image/svg+xml');
      const fr = new FileReader();
      fr.onerror = () => reject(new Error('이미지를 읽지 못했어요.'));
      fr.onload = (e) => {
        const srcDataUrl = e.target.result;
        if (keepOriginal) return resolve({ dataUrl: srcDataUrl, width: null, height: null });
        const img = new Image();
        img.onerror = () => reject(new Error('이미지를 디코딩하지 못했어요.'));
        img.onload = () => {
          const maxSide = Math.max(img.naturalWidth, img.naturalHeight);
          let w = img.naturalWidth, h = img.naturalHeight;
          if (maxSide > maxEdge){
            const ratio = maxEdge / maxSide;
            w = Math.round(w * ratio);
            h = Math.round(h * ratio);
          }
          const canvas = document.createElement('canvas');
          canvas.width = w; canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, w, h);
          // PNG with transparency → keep PNG, else JPEG
          const outMime = (file.type === 'image/png' || file.type === 'image/webp') ? file.type : 'image/jpeg';
          const outUrl = outMime === 'image/jpeg'
            ? canvas.toDataURL('image/jpeg', quality)
            : canvas.toDataURL(outMime);
          resolve({ dataUrl: outUrl, width: w, height: h });
        };
        img.src = srcDataUrl;
      };
      fr.readAsDataURL(file);
    });
  }

  // ---- Figma URL 입력 ----
  function parseFigmaUrlClient(raw){
    // 반환: { ok:true, url, fileKey, nodeId, frameHint } 또는 { ok:false, reason }
    const s = (raw || '').trim();
    if (!s) return { ok:false, reason:'empty' };
    let u;
    try { u = new URL(s); } catch(_) { return { ok:false, reason:'invalid' }; }
    if (!/(^|\.)figma\.com$/i.test(u.hostname)) return { ok:false, reason:'not-figma' };
    const m = u.pathname.match(/\/(file|design|proto)\/([A-Za-z0-9]+)(?:\/([^\/?#]+))?/);
    if (!m) return { ok:false, reason:'no-file-key' };
    const fileKey = m[2];
    const frameHint = m[3] ? decodeURIComponent(m[3]).replace(/-/g,' ') : '';
    const nodeIdRaw = u.searchParams.get('node-id');
    if (!nodeIdRaw) return { ok:false, reason:'no-node' };
    // Figma API 는 node-id 를 "12:345" 형식으로 원함. URL 에는 "12-345" 로 옴.
    const nodeId = nodeIdRaw.replace(/-/g, ':');
    return { ok:true, url:s, fileKey, nodeId, frameHint };
  }

  function setFigmaStatus(state, text){
    const box = $('#figmaPreview');
    const label = $('#figmaPreviewText');
    box.classList.remove('show','loading','error');
    if (!state){ return; }
    box.classList.add('show');
    if (state === 'loading') box.classList.add('loading');
    if (state === 'error')   box.classList.add('error');
    label.textContent = text || '';
  }

  function onFigmaUrlChange(raw){
    const r = parseFigmaUrlClient(raw);
    const btn = $('#analyzeBtn');
    if (r.ok) {
      figmaUrlOk = true;
      figmaParsedUrl = r.url;
      figmaFrameName = r.frameHint || 'Figma frame';
      setFigmaStatus('ok', `프레임 확인됨 · ${r.frameHint || r.fileKey} (node ${r.nodeId})`);
      btn.disabled = false;
      $('#btnText').textContent = '검수 시작';
      hideBanner();
    } else {
      figmaUrlOk = false;
      figmaParsedUrl = '';
      figmaFrameName = '';
      btn.disabled = true;
      if (r.reason === 'empty') {
        setFigmaStatus('');
        $('#btnText').textContent = 'Figma URL을 입력해 주세요';
      } else if (r.reason === 'no-node') {
        setFigmaStatus('error', 'node-id가 없어요 → Figma에서 특정 프레임을 선택한 뒤 우클릭 → "Copy link to selection"으로 복사해주세요.');
        $('#btnText').textContent = 'URL에 node-id가 필요해요';
      } else if (r.reason === 'not-figma') {
        setFigmaStatus('error', 'figma.com URL이 아니에요.');
        $('#btnText').textContent = 'Figma URL을 입력해 주세요';
      } else {
        setFigmaStatus('error', '유효하지 않은 Figma URL이에요.');
        $('#btnText').textContent = 'Figma URL을 입력해 주세요';
      }
    }
  }

  if (PAGE_MODE === 'figma') {
    const urlInput = $('#figmaUrlInput');
    urlInput.addEventListener('input', (e) => onFigmaUrlChange(e.target.value));
    urlInput.addEventListener('paste', (e) => {
      // paste 직후 값이 세팅되도록 다음 tick 에 처리
      setTimeout(() => onFigmaUrlChange(urlInput.value), 0);
    });
    // 드롭존에 URL 텍스트 드롭 지원
    const fdz = $('#figmaDropZone');
    ['dragenter','dragover'].forEach(ev => fdz.addEventListener(ev, e => { e.preventDefault(); fdz.classList.add('active'); }));
    ['dragleave','drop'].forEach(ev => fdz.addEventListener(ev, e => { e.preventDefault(); fdz.classList.remove('active'); }));
    fdz.addEventListener('drop', e => {
      const txt = (e.dataTransfer && (e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain'))) || '';
      if (txt) {
        urlInput.value = txt.trim();
        onFigmaUrlChange(urlInput.value);
        urlInput.focus();
      }
    });
    // 초기 상태: 버튼 텍스트
    $('#btnText').textContent = 'Figma URL을 입력해 주세요';
  }

  async function handleFile(file){
    if (!file.type.startsWith('image/')){ showBanner('이미지 파일만 업로드할 수 있어요.'); return; }
    selectedFile = file;
    $('#fileName').textContent = file.name + ' · 최적화 중…';
    const btn = $('#analyzeBtn');
    btn.disabled = true;
    hideBanner();
    try {
      const { dataUrl } = await downscaleImage(file, 2048, 0.85);
      selectedDataUrl = dataUrl;
      $('#previewImg').src = selectedDataUrl;
      $('#preview').classList.add('show');
      $('#fileName').textContent = file.name;
      btn.disabled = false;
      $('#btnText').textContent = '검수 시작';
    } catch(err){
      showBanner('오류: ' + (err.message || '이미지 처리 실패'));
      $('#fileName').textContent = '';
      selectedFile = null;
      selectedDataUrl = null;
    }
  }

  function showBanner(msg, type){
    const b = $('#banner');
    b.textContent = msg;
    b.classList.toggle('error', type === 'error');
    b.classList.add('show');
  }
  function hideBanner(){ $('#banner').classList.remove('show','error'); }

  let lastResult = null;

  function startProgress(seconds){
    const btn = $('#analyzeBtn');
    btn.classList.remove('loading');
    btn.style.setProperty('--progress-dur', seconds + 's');
    // Force reflow so the transition restarts cleanly from 0
    void btn.offsetWidth;
    btn.classList.add('loading');
  }
  function stopProgress(){
    const btn = $('#analyzeBtn');
    btn.classList.remove('loading');
    btn.style.removeProperty('--progress-dur');
  }

  $('#analyzeBtn').addEventListener('click', async () => {
    const btn = $('#analyzeBtn');

    if (PAGE_MODE === 'figma') {
      if (!figmaUrlOk || !figmaParsedUrl) { showBanner('유효한 Figma URL을 입력해 주세요.'); return; }
      btn.disabled = true;
      $('#btnText').textContent = 'Figma 렌더링 후 검수 중… (최대 80초)';
      startProgress(80);
      try {
        const r = await fetch('/api/review-figma', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            figmaUrl: figmaParsedUrl,
            mediaType: currentMedia,
            subtype: currentSubtype,
            extras: extraChecks,
            context: $('#context').value || ''
          })
        });
        if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || '요청 실패');
        lastResult = data;
        stopProgress();
        render(data);
      } catch(err) {
        stopProgress();
        showBanner('오류: ' + err.message, 'error');
        btn.disabled = false;
        $('#btnText').textContent = '다시 시도';
      }
      return;
    }

    // image mode (기존 동작)
    if(!selectedFile || !selectedDataUrl){ showBanner('이미지를 먼저 업로드해 주세요.'); return; }
    btn.disabled = true;
    $('#btnText').textContent = '검수 중… (최대 60초)';
    startProgress(60);

    try{
      const r = await fetch('/api/review', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          image: selectedDataUrl,
          mediaType: currentMedia,
          subtype: currentSubtype,
          extras: extraChecks,
          context: $('#context').value || ''
        })
      });
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || '요청 실패');
      lastResult = data;
      stopProgress();
      render(data);
    } catch(err){
      stopProgress();
      showBanner('오류: ' + err.message, 'error');
      btn.disabled = false;
      $('#btnText').textContent = '다시 시도';
    }
  });

  const CATEGORY_KO = {
    food:'음식', space:'공간', people:'인물',
    logo:'로고', event:'이벤트', graphic:'그래픽', other:'기타'
  };
  const SUBSCORE_LABELS = [
    ['tone',             '톤·색감'],
    ['typography',       '타이포그래피'],
    ['composition',      '구도'],
    ['imageQuality',     '이미지 품질'],
    ['textImageHarmony', '텍스트·이미지 조화'],
    ['brandFit',         '브랜드 적합도'],
  ];

  function render(d){
    document.querySelector('.input-phase').style.display = 'none';
    $('#resultPhase').classList.add('show');

    if (selectedDataUrl) {
      $('#resultThumbImg').src = selectedDataUrl;
      $('#resultThumbName').textContent = (selectedFile && selectedFile.name) || '업로드한 이미지';
      $('#resultThumb').classList.add('show');
    } else if (d._thumb) {
      $('#resultThumbImg').src = d._thumb;
      $('#resultThumbName').textContent = d._thumbName || (d._figmaFrame ? ('Figma · ' + d._figmaFrame) : '공유된 검수 결과');
      $('#resultThumb').classList.add('show');
    }

    const score = clamp(parseInt(d.overallScore ?? 0, 10), 0, 100);
    animateScore(score);
    animateRing(score);
    $('#scoreLabel').textContent = scoreLabel(score);
    $('#resultSub').textContent = d.summary || '—';
    $('#summary').textContent = d.summary || '—';

    const badge = $('#categoryBadge');
    if (d.category) {
      badge.textContent = CATEGORY_KO[d.category] || d.category;
      badge.style.display = 'inline-block';
    } else { badge.style.display = 'none'; }

    const meta = d.subscores || {};
    const cells = SUBSCORE_LABELS.map(([k, l]) => [l, meta[k]]).filter(([,v]) => v != null);
    $('#metaGrid').innerHTML = cells.map(([k,v]) => {
      const cls = v >= 80 ? 'ok' : v >= 60 ? 'warn' : 'bad';
      return `<div class="cell"><div class="k">${escapeHtml(k)}</div><div class="v ${cls}">${v}</div></div>`;
    }).join('') || '';

    fillList('#strengths', d.strengths || []);
    fillList('#improvements', d.improvements || []);
    window.scrollTo({top:0, behavior:'smooth'});
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
  function animateRing(target){
    const CIRC = 2 * Math.PI * 56; // r=56
    const ring = $('#scoreRing');
    if (!ring) return;
    ring.setAttribute('stroke-dasharray', CIRC.toFixed(2));
    // triggering transition
    ring.setAttribute('stroke-dashoffset', CIRC.toFixed(2));
    requestAnimationFrame(() => {
      const off = CIRC * (1 - clamp(target, 0, 100)/100);
      ring.setAttribute('stroke-dashoffset', off.toFixed(2));
    });
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

  // 상태에 따라 버튼/문구를 초기화
  function resetAnalyzeButton(){
    if (PAGE_MODE === 'figma') {
      $('#analyzeBtn').disabled = !figmaUrlOk;
      $('#btnText').textContent = figmaUrlOk ? '검수 시작' : 'Figma URL을 입력해 주세요';
    } else {
      $('#analyzeBtn').disabled = !selectedDataUrl;
      $('#btnText').textContent = selectedDataUrl ? '검수 시작' : '이미지를 업로드해 주세요';
    }
  }

  // 새 이미지/링크로 검수하기: 전체 리셋
  $('#backBtn').addEventListener('click', () => {
    document.querySelector('.input-phase').style.display = '';
    $('#resultPhase').classList.remove('show');
    $('#resultThumb').classList.remove('show');
    resetAnalyzeButton();
    hideBanner();
    window.scrollTo({top:0, behavior:'smooth'});
  });
  // 모드에 맞춰 "새 ~로 검수하기" 문구도 바꿔줌
  $('#backBtn').textContent = PAGE_MODE === 'figma' ? '← 새 Figma 링크로 검수하기' : '← 새 이미지로 검수하기';

  // 매체 타입만 바꿔서 재검수: 이미지/URL 상태 유지
  $('#btnReanalyze').addEventListener('click', () => {
    document.querySelector('.input-phase').style.display = '';
    $('#resultPhase').classList.remove('show');
    hideBanner();
    $('#analyzeBtn').disabled = (PAGE_MODE === 'figma') ? !figmaUrlOk : !selectedDataUrl;
    $('#btnText').textContent = '검수 시작';
    window.scrollTo({top:0, behavior:'smooth'});
    // 포커스를 매체 선택 카드로
    setTimeout(() => { $('#seg').scrollIntoView({behavior:'smooth', block:'center'}); }, 450);
  });

  // 텍스트 복사
  $('#btnCopy').addEventListener('click', async () => {
    if (!lastResult) return;
    const d = lastResult;
    const subLines = SUBSCORE_LABELS
      .map(([k,l]) => (d.subscores && d.subscores[k] != null) ? `- ${l}: ${d.subscores[k]}` : null)
      .filter(Boolean).join('\\n');
    const cat = d.category ? (CATEGORY_KO[d.category] || d.category) : '';
    const md = [
      `# 브랜드 톤앤매너 검수 결과`,
      cat ? `카테고리: ${cat}` : null,
      `종합 점수: ${d.overallScore || 0} / 100`,
      '',
      `## 요약`,
      d.summary || '—',
      '',
      `## 세부 점수`,
      subLines || '—',
      '',
      `## 강점`,
      ...(d.strengths||[]).map(x => `- ${x}`),
      '',
      `## 개선점`,
      ...(d.improvements||[]).map(x => `- ${x}`),
    ].filter(x => x !== null).join('\\n');
    try{
      await navigator.clipboard.writeText(md);
      flashBtn('#btnCopy', '복사됨 ✓');
    } catch(e){
      showBanner('클립보드 복사에 실패했어요. 브라우저 권한을 확인해주세요.', 'error');
    }
  });

  // 공유 링크 복사
  $('#btnShareUrl').addEventListener('click', async () => {
    if (!lastResult || !lastResult.reviewId) {
      showBanner('공유할 결과 ID가 없습니다.', 'error'); return;
    }
    const url = location.origin + '/r/' + lastResult.reviewId;
    try{
      await navigator.clipboard.writeText(url);
      flashBtn('#btnShareUrl', '링크 복사됨 ✓');
    } catch(e){
      showBanner('클립보드 복사에 실패했어요.', 'error');
    }
  });

  // 이미지 저장 (결과 카드 영역을 PNG 로)
  $('#btnDownload').addEventListener('click', async () => {
    const btn = $('#btnDownload');
    btn.disabled = true;
    const prevLabel = btn.innerHTML;
    btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;border-width:2px"></span> 생성 중…';
    try{
      await ensureHtml2Canvas();
      const el = document.querySelector('#resultPhase');
      // html2canvas 가 oklch / 최신 컬러함수 지원이 약해 배경색 명시
      const canvas = await window.html2canvas(el, {
        backgroundColor: '#0a0a0a', scale: 2, useCORS: true, logging: false,
      });
      const link = document.createElement('a');
      link.href = canvas.toDataURL('image/png');
      link.download = 'brand-review-' + (new Date().toISOString().slice(0,16).replace(/[:T]/g,'')) + '.png';
      link.click();
    } catch(e){
      showBanner('이미지 생성에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = prevLabel;
    }
  });

  function ensureHtml2Canvas(){
    if (window.html2canvas) return Promise.resolve();
    return new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
      s.onload = res; s.onerror = () => rej(new Error('html2canvas load failed'));
      document.head.appendChild(s);
    });
  }

  function flashBtn(sel, text){
    const b = document.querySelector(sel);
    const prev = b.innerHTML;
    b.innerHTML = text;
    b.classList.add('on');
    setTimeout(() => { b.innerHTML = prev; b.classList.remove('on'); }, 1400);
  }

  // 공유 URL 경로로 진입한 경우 결과를 로드
  (async function bootstrapSharedResult(){
    const rid = document.body.dataset.sharedResult;
    if (!rid) return;
    try{
      const r = await fetch('/api/result/' + encodeURIComponent(rid));
      if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname); return; }
      if (!r.ok) throw new Error('만료되었거나 존재하지 않는 공유 링크입니다.');
      const data = await r.json();
      lastResult = data;
      render(data);
    } catch(err){
      document.querySelector('.input-phase').style.display = '';
      showBanner('공유된 결과를 불러오지 못했어요: ' + err.message, 'error');
    }
  })();
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


# ---------------------------------------------------------------------------
# Figma integration
# ---------------------------------------------------------------------------
_FIGMA_URL_RE = re.compile(
    r"^https?://(?:www\.)?figma\.com/(file|design|proto)/"
    r"(?P<key>[A-Za-z0-9]+)(?:/(?P<slug>[^/?#]+))?",
    re.IGNORECASE,
)


def parse_figma_url(url: str):
    """Parse a Figma URL.

    Returns dict(file_key, node_id, frame_hint) or raises ValueError.
    Expects a URL like:
      https://www.figma.com/design/ABC123/MyFile?node-id=12-345
    node-id must be present; dashes are converted to ':' for the Figma API.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Figma URL이 비어있습니다.")
    url = url.strip()
    m = _FIGMA_URL_RE.match(url)
    if not m:
        raise ValueError("유효하지 않은 Figma URL입니다. (figma.com 주소여야 합니다)")
    file_key = m.group("key")
    slug = m.group("slug") or ""
    frame_hint = ""
    if slug:
        try:
            from urllib.parse import unquote
            frame_hint = unquote(slug).replace("-", " ")
        except Exception:
            frame_hint = slug
    # node-id 추출 (querystring 에서)
    try:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(url).query)
        node_raw = (qs.get("node-id") or [""])[0]
    except Exception:
        node_raw = ""
    if not node_raw:
        raise ValueError(
            "URL에 node-id가 없어요. Figma에서 특정 프레임을 선택한 뒤 "
            "우클릭 → \"Copy link to selection\"으로 복사해주세요."
        )
    node_id = node_raw.replace("-", ":")
    return {"file_key": file_key, "node_id": node_id, "frame_hint": frame_hint}


def fetch_figma_image(file_key: str, node_id: str, *, scale: str = None, timeout: int = 50):
    """Ask Figma to render the given node as PNG, then download the bytes.

    Returns (png_bytes, frame_name) where frame_name is best-effort.
    Raises RuntimeError with a user-friendly message on failure.
    """
    if not FIGMA_TOKEN:
        raise RuntimeError(
            "서버에 FIGMA_TOKEN이 설정되어 있지 않아요. 관리자에게 문의해주세요."
        )
    scale = scale or FIGMA_RENDER_SCALE or "1.5"
    headers = {"X-Figma-Token": FIGMA_TOKEN}
    # 1) 이미지 렌더 요청
    img_url = (
        f"https://api.figma.com/v1/images/{file_key}"
        f"?ids={node_id}&format=png&scale={scale}"
    )
    try:
        r = requests.get(img_url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Figma 서버와 연결에 실패했어요: {exc}") from exc
    if r.status_code == 403:
        raise RuntimeError(
            "Figma 파일에 접근할 수 없어요. 토큰의 권한 또는 파일 공유 설정을 확인해주세요."
        )
    if r.status_code == 404:
        raise RuntimeError(
            "해당 Figma 파일이나 노드를 찾을 수 없어요. URL을 다시 확인해주세요."
        )
    if r.status_code != 200:
        snippet = (r.text or "")[:200].replace("\n", " ")
        raise RuntimeError(f"Figma API 오류 (HTTP {r.status_code}): {snippet}")

    body = r.json() or {}
    if body.get("err"):
        raise RuntimeError(f"Figma API 오류: {body.get('err')}")
    images = body.get("images") or {}
    signed_url = images.get(node_id)
    if not signed_url:
        raise RuntimeError(
            "Figma에서 해당 노드를 렌더링하지 못했어요. 프레임/컴포넌트를 선택한 링크인지 확인해주세요."
        )

    # 2) 실제 PNG 다운로드 (Figma 가 내려준 임시 S3 URL)
    try:
        dl = requests.get(signed_url, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        raise RuntimeError(f"Figma 이미지 다운로드에 실패했어요: {exc}") from exc
    if dl.status_code != 200:
        raise RuntimeError(f"Figma 이미지 다운로드 실패 (HTTP {dl.status_code}).")
    # 최대 20MB 제한 (악의적 페이로드 방지)
    content = b""
    for chunk in dl.iter_content(1 << 15):
        content += chunk
        if len(content) > 20 * 1024 * 1024:
            raise RuntimeError("Figma 이미지가 너무 커요 (20MB 초과). 더 작은 프레임을 선택해주세요.")
    if not content:
        raise RuntimeError("Figma가 빈 이미지를 반환했어요.")

    # 3) 프레임 이름 best-effort (files/nodes 호출)
    frame_name = ""
    try:
        nr = requests.get(
            f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}",
            headers=headers, timeout=15,
        )
        if nr.status_code == 200:
            nb = nr.json() or {}
            nd = ((nb.get("nodes") or {}).get(node_id) or {}).get("document") or {}
            frame_name = nd.get("name", "") or ""
    except Exception:
        pass
    return content, frame_name


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


# ---------------------------------------------------------------------------
# Result store (in-memory, TTL 6h, 최대 200건) — 공유 URL 용
# Render Free 환경은 인스턴스 재기동 시 초기화됨을 명시. 영속 보관이 필요하면 DB 연동 필요.
# ---------------------------------------------------------------------------
_RESULTS_LOCK = threading.Lock()
_RESULTS = {}  # rid -> {data, created_at}
_RESULT_TTL = 6 * 3600
_RESULT_MAX = 200

def _save_result(data: dict) -> str:
    rid = uuid.uuid4().hex[:10]
    now = time.time()
    with _RESULTS_LOCK:
        # prune
        dead = [k for k, v in _RESULTS.items() if now - v["created_at"] > _RESULT_TTL]
        for k in dead:
            _RESULTS.pop(k, None)
        if len(_RESULTS) >= _RESULT_MAX:
            # 가장 오래된 것 제거
            oldest = min(_RESULTS.items(), key=lambda kv: kv[1]["created_at"])
            _RESULTS.pop(oldest[0], None)
        _RESULTS[rid] = {"data": data, "created_at": now}
    return rid

def _get_result(rid: str):
    with _RESULTS_LOCK:
        entry = _RESULTS.get(rid)
        if not entry:
            return None
        if time.time() - entry["created_at"] > _RESULT_TTL:
            _RESULTS.pop(rid, None)
            return None
        return entry["data"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {"/login", "/logout", "/healthz"}

def _auth_enabled() -> bool:
    return bool(APP_PASSWORD)

def _is_authed() -> bool:
    return not _auth_enabled() or bool(session.get("auth"))

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_authed():
            if request.path.startswith("/api/"):
                return jsonify(error="인증이 필요합니다.", needsLogin=True), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

LOGIN_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0a0a0a">
<title>로그인 · CatchTable 브랜드 검수</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{background:#0a0a0a;color:#fff;min-height:100vh;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Noto Sans KR",Roboto,sans-serif}
  .wrap{max-width:380px;margin:0 auto;padding:120px 24px}
  h1{font-size:22px;font-weight:700;margin-bottom:8px;letter-spacing:-.01em}
  p.sub{color:#9a9a9a;font-size:14px;margin-bottom:28px;line-height:1.6}
  label{display:block;font-size:12px;color:#6b6b6b;letter-spacing:.08em;
    text-transform:uppercase;margin-bottom:10px}
  input{width:100%;padding:14px 16px;background:#141414;border:1px solid #2a2a2a;
    border-radius:10px;color:#fff;font-size:15px;font-family:inherit}
  input:focus{outline:none;border-color:#ff6b35}
  button{width:100%;margin-top:14px;padding:14px;border:0;border-radius:10px;
    background:#ff6b35;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
  button:hover{background:#ff8a5c}
  .err{margin-top:14px;padding:10px 12px;border-radius:8px;background:#2a1f12;
    border:1px solid #4a3522;color:#f6c453;font-size:13px}
</style></head><body><div class="wrap">
  <h1>CatchTable 브랜드 검수</h1>
  <p class="sub">내부 전용 도구입니다. 공유받은 비밀번호를 입력해주세요.</p>
  <form method="post" action="/login">
    <input type="hidden" name="next" value="__NEXT__">
    <label for="pw">비밀번호</label>
    <input id="pw" type="password" name="password" autocomplete="current-password" autofocus required>
    <button type="submit">접속</button>
    __ERR__
  </form>
</div></body></html>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _auth_enabled():
        return redirect(url_for("index"))
    if request.method == "POST":
        provided = (request.form.get("password") or "").strip()
        nxt = request.form.get("next") or "/"
        if not nxt.startswith("/"):
            nxt = "/"
        if secrets.compare_digest(provided, APP_PASSWORD):
            session.permanent = True
            session["auth"] = True
            session["sid"] = session.get("sid") or uuid.uuid4().hex
            log.info("login success from %s", request.remote_addr)
            return redirect(nxt)
        log.info("login fail from %s", request.remote_addr)
        html = LOGIN_HTML.replace("__NEXT__", nxt).replace(
            "__ERR__", '<div class="err">비밀번호가 올바르지 않습니다.</div>')
        return Response(html, mimetype="text/html; charset=utf-8"), 401
    nxt = request.args.get("next", "/")
    if not nxt.startswith("/"):
        nxt = "/"
    html = LOGIN_HTML.replace("__NEXT__", nxt).replace("__ERR__", "")
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("login") if _auth_enabled() else url_for("index"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
@login_required
def index():
    html = INDEX_HTML
    if not _auth_enabled():
        # 비번이 꺼져있으면 footer 의 로그아웃 버튼을 숨김
        html = html.replace(
            '<form method="post" action="/logout" class="logout-form"',
            '<form method="post" action="/logout" class="logout-form" style="display:none"',
            1,
        )
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(
        ok=True,
        geminiConfigured=bool(GEMINI_API_KEY),
        figmaConfigured=bool(FIGMA_TOKEN),
        authEnabled=_auth_enabled(),
        models=GEMINI_MODELS,
    )


@app.route("/debug/list-models", methods=["GET"])
def list_models():
    """Gated: admin 전용. ADMIN_TOKEN 환경변수와 일치하는 ?token=... 필요."""
    provided = (request.args.get("token") or "").strip()
    if not ADMIN_TOKEN or not secrets.compare_digest(provided, ADMIN_TOKEN):
        return jsonify(error="Not found"), 404
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
@login_required
def review():
    req_id = uuid.uuid4().hex[:8]
    try:
        # Rate limit (per-session if authed, else per-IP)
        rl_key = session.get("sid") or f"ip:{request.remote_addr}"
        ok, msg = _rate_limit_check(rl_key)
        if not ok:
            log.info("[%s] rate limited key=%s", req_id, rl_key)
            return jsonify(error=msg), 429

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

        if not GEMINI_API_KEY:
            log.error("[%s] GEMINI_API_KEY not configured", req_id)
            return jsonify(error="검수 엔진이 설정되지 않았습니다. 관리자에게 문의해주세요."), 503

        try:
            result = call_gemini(prompt, mime, b64)
            result.setdefault("source", "gemini")
            # 결과 임시 저장 (공유 URL 용). TTL = 6h, 최대 200건.
            rid = _save_result(result)
            result["reviewId"] = rid
            log.info("[%s] review ok model=%s score=%s",
                     req_id, result.get("modelUsed"), result.get("overallScore"))
            return jsonify(result)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] Gemini failed: %s", req_id, str(exc)[:240])
            return jsonify(
                error="일시적으로 검수를 완료하지 못했어요. 잠시 후 다시 시도해주세요.",
                requestId=req_id,
            ), 503

    except Exception:  # noqa: BLE001
        log.exception("[%s] review failed", req_id)
        return jsonify(
            error="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            requestId=req_id,
        ), 500


@app.route("/figma", methods=["GET"])
@login_required
def figma_page():
    """Figma URL 기반 검수 페이지. INDEX_HTML 을 재사용하되 body 에 모드 플래그를 박는다."""
    html = INDEX_HTML.replace("<body>", '<body data-mode="figma">', 1)
    if not _auth_enabled():
        html = html.replace(
            '<form method="post" action="/logout" class="logout-form"',
            '<form method="post" action="/logout" class="logout-form" style="display:none"',
            1,
        )
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/api/review-figma", methods=["POST"])
@login_required
def review_figma():
    """Figma URL 을 받아 해당 프레임을 PNG 로 렌더 후 기존 검수 파이프라인에 태운다."""
    req_id = uuid.uuid4().hex[:8]
    try:
        rl_key = session.get("sid") or f"ip:{request.remote_addr}"
        ok, msg = _rate_limit_check(rl_key)
        if not ok:
            log.info("[%s] rate limited key=%s", req_id, rl_key)
            return jsonify(error=msg), 429

        data = request.get_json(silent=True) or {}
        figma_url = (data.get("figmaUrl") or "").strip()
        media_type = data.get("mediaType", "social")
        subtype = data.get("subtype", "")
        extras = data.get("extras", []) or []
        context = data.get("context", "")

        if not figma_url:
            return jsonify(error="Figma URL이 비어있습니다."), 400

        # 1) URL 파싱
        try:
            parsed = parse_figma_url(figma_url)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        # 2) Figma 렌더 + 이미지 다운로드
        try:
            png_bytes, frame_name = fetch_figma_image(parsed["file_key"], parsed["node_id"])
        except RuntimeError as exc:
            log.warning("[%s] figma fetch failed: %s", req_id, exc)
            return jsonify(error=str(exc)), 502

        # 3) Gemini 호출 (기존 파이프라인 재사용)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        # 제작 맥락에 Figma 프레임 이름을 덧붙여 힌트 제공
        display_name = frame_name or parsed.get("frame_hint") or "Figma frame"
        base_ctx = (context or "").strip()
        suffix = f"(Figma 프레임: {display_name})" if display_name else ""
        extended_context = (base_ctx + " " + suffix).strip() if base_ctx and suffix else (base_ctx or suffix)
        prompt = build_prompt(media_type, subtype, extras, extended_context)

        if not GEMINI_API_KEY:
            log.error("[%s] GEMINI_API_KEY not configured", req_id)
            return jsonify(error="검수 엔진이 설정되지 않았습니다. 관리자에게 문의해주세요."), 503

        try:
            result = call_gemini(prompt, "image/png", b64)
            result.setdefault("source", "gemini-figma")
            # 썸네일을 결과에 포함 (공유 URL 에서도 보이도록)
            data_url = "data:image/png;base64," + b64
            result["_thumb"] = data_url
            result["_thumbName"] = f"Figma · {display_name}"
            result["_figmaUrl"] = figma_url
            result["_figmaFrame"] = display_name
            rid = _save_result(result)
            result["reviewId"] = rid
            log.info(
                "[%s] figma review ok model=%s score=%s key=%s node=%s",
                req_id, result.get("modelUsed"), result.get("overallScore"),
                parsed["file_key"], parsed["node_id"],
            )
            return jsonify(result)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] Gemini failed: %s", req_id, str(exc)[:240])
            return jsonify(
                error="일시적으로 검수를 완료하지 못했어요. 잠시 후 다시 시도해주세요.",
                requestId=req_id,
            ), 503

    except Exception:  # noqa: BLE001
        log.exception("[%s] review-figma failed", req_id)
        return jsonify(
            error="서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            requestId=req_id,
        ), 500


@app.route("/api/result/<rid>", methods=["GET"])
@login_required
def api_get_result(rid):
    data = _get_result(rid)
    if not data:
        return jsonify(error="만료되었거나 존재하지 않는 결과입니다."), 404
    return jsonify(data)


@app.route("/r/<rid>", methods=["GET"])
@login_required
def share_view(rid):
    # 같은 INDEX_HTML을 내려주고, 클라이언트가 /api/result/<rid> 로 데이터를 로드해 렌더.
    # Hash 에 rid 를 박아 프론트가 감지하도록 함.
    html = INDEX_HTML.replace(
        "<body>",
        f'<body data-shared-result="{rid}">'
    )
    return Response(html, mimetype="text/html; charset=utf-8")


# ---------------------------------------------------------------------------
# Entry point (gunicorn uses app:app, local runs directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
