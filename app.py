import os
import json
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

HTML_CONTENT = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>캐치테이블 브랜드 검수</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', sans-serif;
            background: linear-gradient(135deg, #ffffff 0%, #fff5f0 50%, #ffe8dd 100%);
            min-height: 100vh;
            color: #1f2937;
        }

        header {
            background: white;
            border-bottom: 1px solid #fed7aa;
            padding: 1.5rem;
            text-align: center;
            position: sticky;
            top: 0;
            z-index: 10;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .logo {
            font-size: 1.25rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }

        .logo .catch {
            color: #ea580c;
        }

        .logo .table {
            color: #1f2937;
        }

        .header-text {
            color: #6b7280;
            font-size: 0.875rem;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }

        .input-phase {
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }

        .input-phase.hidden {
            display: none;
        }

        .drop-zone {
            border: 3px dashed #d1d5db;
            border-radius: 1rem;
            padding: 4rem 2rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            background: white;
        }

        .drop-zone:hover {
            border-color: #fed7aa;
            background: #fffaf5;
        }

        .drop-zone.active {
            border-color: #ea580c;
            background: #fef3f2;
            transform: scale(1.02);
        }

        .drop-icon {
            font-size: 4rem;
            margin-bottom: 1rem;
        }

        .drop-text {
            font-size: 1.25rem;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 0.5rem;
        }

        .drop-subtext {
            color: #6b7280;
            margin-bottom: 1.5rem;
            font-size: 0.95rem;
        }

        .file-input {
            display: none;
        }

        .select-btn {
            display: inline-block;
            padding: 0.75rem 2rem;
            background: #ea580c;
            color: white;
            border: none;
            border-radius: 0.5rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .select-btn:hover {
            background: #c2410c;
        }

        .preview-section {
            background: white;
            border: 1px solid #fed7aa;
            border-radius: 0.75rem;
            padding: 1.5rem;
            display: none;
        }

        .preview-section.show {
            display: block;
        }

        .preview-container {
            margin-bottom: 1.5rem;
        }

        .preview-image {
            max-width: 100%;
            max-height: 300px;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
        }

        .preview-info {
            font-size: 0.875rem;
            color: #6b7280;
        }

        .preview-info strong {
            color: #1f2937;
        }

        .meta-section {
            background: white;
            border: 1px solid #fed7aa;
            border-radius: 0.75rem;
            padding: 1.5rem;
        }

        .meta-label {
            display: block;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 0.5rem;
            font-size: 0.95rem;
        }

        .meta-input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 0.5rem;
            font-size: 0.95rem;
            font-family: inherit;
            margin-bottom: 0.75rem;
        }

        .meta-input:focus {
            outline: none;
            border-color: #ea580c;
            box-shadow: 0 0 0 3px rgba(234, 88, 12, 0.1);
        }

        .meta-hint {
            font-size: 0.75rem;
            color: #9ca3af;
            margin-bottom: 1.5rem;
        }

        .media-selector {
            margin-bottom: 1.5rem;
        }

        .media-label-text {
            display: block;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 0.75rem;
            font-size: 0.95rem;
        }

        .media-options {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 0.75rem;
        }

        .media-option {
            padding: 0.75rem;
            border: 2px solid #d1d5db;
            border-radius: 0.5rem;
            background: white;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
        }

        .media-option:hover {
            border-color: #fed7aa;
        }

        .media-option.selected {
            border-color: #ea580c;
            background: #fef3f2;
            font-weight: 600;
        }

        .media-option-icon {
            font-size: 1.5rem;
            margin-bottom: 0.25rem;
        }

        .media-option-name {
            font-size: 0.75rem;
            font-weight: 500;
        }

        .action-buttons {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }

        .btn-analyze {
            flex: 1;
            min-width: 200px;
            padding: 1rem;
            background: #ea580c;
            color: white;
            border: none;
            border-radius: 0.5rem;
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
        }

        .btn-analyze:hover:not(:disabled) {
            background: #c2410c;
        }

        .btn-analyze:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-reset {
            padding: 1rem 1.5rem;
            background: white;
            color: #ea580c;
            border: 2px solid #ea580c;
            border-radius: 0.5rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .btn-reset:hover {
            background: #fef3f2;
        }

        .spinner {
            width: 1.25rem;
            height: 1.25rem;
            border: 2px solid white;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .results-phase {
            display: none;
        }

        .results-phase.show {
            display: block;
        }

        .results-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            flex-wrap: wrap;
            gap: 1rem;
        }

        .results-title {
            font-size: 2rem;
            font-weight: bold;
            color: #1f2937;
        }

        .reset-btn {
            padding: 0.75rem 1.5rem;
            background: white;
            border: 2px solid #ea580c;
            color: #ea580c;
            border-radius: 0.5rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .reset-btn:hover {
            background: #fef3f2;
        }

        .score-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .score-card {
            border-radius: 0.75rem;
            padding: 2rem;
            color: white;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .score-card.worst {
            background: linear-gradient(135deg, #ea580c 0%, #c2410c 100%);
        }

        .score-card.overall {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        }

        .score-card.grade {
            background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
        }

        .score-label {
            font-size: 0.875rem;
            font-weight: 600;
            opacity: 0.9;
            margin-bottom: 0.5rem;
        }

        .score-number {
            font-size: 3rem;
            font-weight: bold;
            margin-bottom: 0.75rem;
        }

        .info-card {
            background: white;
            border: 1px solid #fed7aa;
            border-radius: 0.75rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }

        .info-title {
            font-weight: 700;
            color: #1f2937;
            margin-bottom: 1rem;
            font-size: 1.1rem;
        }

        .summary-text {
            color: #4b5563;
            line-height: 1.6;
            margin-bottom: 1rem;
        }

        footer {
            border-top: 1px solid #e5e7eb;
            background: white;
            margin-top: 4rem;
            padding: 2rem;
            text-align: center;
            color: #6b7280;
            font-size: 0.875rem;
        }

        .hidden {
            display: none;
        }

        @media (max-width: 768px) {
            .drop-zone {
                padding: 2.5rem 1rem;
            }

            .drop-text {
                font-size: 1.1rem;
            }

            .drop-icon {
                font-size: 3rem;
            }

            .score-number {
                font-size: 2.5rem;
            }

            .action-buttons {
                flex-direction: column;
            }

            .btn-analyze {
                min-width: auto;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="logo">
            <span class="catch">캐치</span><span class="table">테이블</span>
        </div>
        <div class="header-text">브랜드 가이드 1차 검수 - 이미지를 드래그&드롭하기만 하면 AI가 검수해줍니다</div>
    </header>

    <div class="container">
        <div class="input-phase">
            <div class="drop-zone" id="dropZone">
                <div class="drop-icon">📷</div>
                <div class="drop-text">이미지를 여기에 놓으세요</div>
                <div class="drop-subtext">또는 아래에서 파일 선택</div>
                <input type="file" id="fileInput" class="file-input" accept="image/*">
                <button class="select-btn" onclick="document.getElementById('fileInput').click()">파일 선택</button>
            </div>

            <div class="preview-section" id="previewSection">
                <div class="preview-container">
                    <img id="previewImage" class="preview-image" alt="Preview">
                    <div class="preview-info">
                        파일명: <strong id="fileName"></strong> | 크기: <strong id="fileSize"></strong>
                    </div>
                </div>
            </div>

            <div class="meta-section">
                <label class="meta-label">📝 매체 타입</label>
                <div class="media-selector">
                    <span class="media-label-text">검수할 콘텐츠 유형:</span>
                    <div class="media-options" id="mediaOptions">
                        <button class="media-option selected" data-media="online">
                            <div class="media-option-icon">📱</div>
                            <div class="media-option-name">온라인</div>
                        </button>
                        <button class="media-option" data-media="print">
                            <div class="media-option-icon">📄</div>
                            <div class="media-option-name">인쇄물</div>
                        </button>
                        <button class="media-option" data-media="video">
                            <div class="media-option-icon">🎬</div>
                            <div class="media-option-name">영상</div>
                        </button>
                    </div>
                </div>

                <label class="meta-label">💬 제작 맥락 (선택사항)</label>
                <textarea class="meta-input" id="context" rows="2" placeholder="예: 4월 미식 가이드 세로형 배너"></textarea>
                <div class="meta-hint">제작 맥락을 입력하면 더 정확한 검수가 가능합니다</div>
            </div>

            <div class="action-buttons">
                <button class="btn-analyze" id="analyzeBtn" disabled>
                    <span>🚀 검수 시작</span>
                </button>
            </div>
        </div>

        <div class="results-phase" id="resultsPhase">
            <div class="results-header">
                <h1 class="results-title">검수 결과</h1>
                <button class="reset-btn" onclick="location.reload()">새로 검수하기</button>
            </div>

            <div class="score-cards">
                <div class="score-card overall">
                    <div class="score-label">종합 점수</div>
                    <div class="score-number" id="totalScore">78</div>
                </div>
            </div>

            <div class="info-card">
                <div class="info-title">📋 검수 결과</div>
                <div class="summary-text" id="summaryContent"></div>
            </div>

            <div class="info-card">
                <div class="info-title">💡 권장사항</div>
                <div class="summary-text" id="recommendationContent"></div>
            </div>
        </div>
    </div>

    <footer>
        © 2024 CatchTable. 브랜드 가이드 검수 자동화 도구
    </footer>

    <script>
        let selectedFile = null;
        let currentMedia = 'online';

        document.querySelectorAll('.media-option').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.media-option').forEach(b => b.classList.remove('selected'));
                this.classList.add('selected');
                currentMedia = this.dataset.media;
            });
        });

        const dropZone = document.getElementById('dropZone');

        dropZone.addEventListener('dragover', e => {
            e.preventDefault();
            dropZone.classList.add('active');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('active');
        });

        dropZone.addEventListener('drop', e => {
            e.preventDefault();
            dropZone.classList.remove('active');
            const files = Array.from(e.dataTransfer.files);
            if (files.length > 0) {
                handleFile(files[0]);
            }
        });

        document.getElementById('fileInput').addEventListener('change', e => {
            if (e.target.files.length > 0) {
                handleFile(e.target.files[0]);
            }
        });

        function handleFile(file) {
            selectedFile = file;

            const reader = new FileReader();
            reader.onload = e => {
                document.getElementById('previewImage').src = e.target.result;
                document.getElementById('previewSection').classList.add('show');
            };
            reader.readAsDataURL(file);

            document.getElementById('fileName').textContent = file.name;
            document.getElementById('fileSize').textContent = (file.size / 1024 / 1024).toFixed(2) + ' MB';

            document.getElementById('analyzeBtn').disabled = false;
        }

        document.getElementById('analyzeBtn').addEventListener('click', async () => {
            if (!selectedFile) {
                alert('파일을 선택해주세요');
                return;
            }

            const btn = document.getElementById('analyzeBtn');
            btn.innerHTML = '<div class="spinner"></div> 검수 중...';
            btn.disabled = true;

            try {
                const reader = new FileReader();
                reader.onload = async (e) => {
                    const imageData = e.target.result;
                    const context = document.getElementById('context').value;

                    const response = await fetch('/api/review', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            image: imageData,
                            mediaType: currentMedia,
                            context: context
                        })
                    });

                    if (!response.ok) {
                        throw new Error('API 요청 실패');
                    }

                    const result = await response.json();
                    showResults(result);
                };
                reader.readAsDataURL(selectedFile);

            } catch (error) {
                console.error('오류:', error);
                alert('검수 중 오류: ' + error.message);
                btn.innerHTML = '<span>🚀 검수 시작</span>';
                btn.disabled = false;
            }
        });

        function showResults(result) {
            document.getElementById('totalScore').textContent = result.overallScore || 75;
            document.getElementById('summaryContent').textContent = result.recommendation || '검수 완료';

            const improvements = result.improvements ? result.improvements.join(', ') : '없음';
            document.getElementById('recommendationContent').textContent = improvements;

            document.querySelector('.input-phase').style.display = 'none';
            document.getElementById('resultsPhase').classList.add('show');
            window.scrollTo(0, 0);
        }
    </script>
</body>
</html>"""

@app.route('/')
def index():
    """메인 페이지"""
    return HTML_CONTENT, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/review', methods=['POST'])
def review():
    """브랜드 검수 API"""
    try:
        data = request.get_json()
        image_data = data.get('image', '')
        media_type = data.get('mediaType', 'online')
        context = data.get('context', '')

        if not image_data or not GEMINI_API_KEY:
            return jsonify({
                'overallScore': 0,
                'recommendation': '이미지 또는 API 키가 없습니다',
                'improvements': []
            }), 400

        # Base64 처리
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)

        # Gemini API 호출
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

        prompt = f"""당신은 전문적인 브랜드 검수 전문가입니다.
제공된 이미지를 분석하여 다음을 평가해주세요:
- 브랜드 일관성
- 디자인 품질
- 가독성
- 전문성

매체: {media_type}
맥락: {context}

JSON 형식으로만 응답하세요:
{{
    "overallScore": 75,
    "recommendation": "평가 및 권장사항",
    "strengths": ["강점1", "강점2"],
    "improvements": ["개선사항1", "개선사항2"]
}}"""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_data
                        }
                    }
                ]
            }]
        }

        response = requests.post(
            f"{url}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            return jsonify({
                'overallScore': 50,
                'recommendation': 'API 호출 실패',
                'improvements': []
            }), 400

        response_data = response.json()
        response_text = response_data['candidates'][0]['content']['parts'][0]['text']

        # JSON 추출
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}') + 1

        if start_idx >= 0 and end_idx > start_idx:
            json_str = response_text[start_idx:end_idx]
            result = json.loads(json_str)
        else:
            result = {
                'overallScore': 75,
                'recommendation': response_text,
                'improvements': []
            }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'overallScore': 0,
            'recommendation': f'오류: {str(e)}',
            'improvements': []
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
