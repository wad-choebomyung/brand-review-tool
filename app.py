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

        .media-options {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 0.75rem;
            margin-bottom: 1.5rem;
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

        .media-option.selected {
            border-color: #ea580c;
            background: #fef3f2;
            font-weight: 600;
        }

        .action-buttons {
            display: flex;
            gap: 1rem;
        }

        .btn-analyze {
            flex: 1;
            padding: 1rem;
            background: #ea580c;
            color: white;
            border: none;
            border-radius: 0.5rem;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
        }

        .btn-analyze:disabled {
            opacity: 0.5;
            cursor: not-allowed;
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
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }

        .results-title {
            font-size: 2rem;
            font-weight: bold;
        }

        .reset-btn {
            padding: 0.75rem 1.5rem;
            background: #ea580c;
            color: white;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-weight: 600;
        }

        .score-card {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
            color: white;
            padding: 2rem;
            border-radius: 0.75rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .score-number {
            font-size: 3rem;
            font-weight: bold;
            margin: 1rem 0;
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
            margin-bottom: 1rem;
            font-size: 1.1rem;
        }

        .summary-text {
            color: #4b5563;
            line-height: 1.6;
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
    </style>
</head>
<body>
    <header>
        <div class="logo">
            <span class="catch">캐치</span><span class="table">테이블</span>
        </div>
        <div class="header-text">브랜드 가이드 1차 검수 - AI가 자동으로 검수합니다</div>
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
                <div>
                    <img id="previewImage" class="preview-image" alt="Preview">
                    <div class="preview-info">
                        파일명: <strong id="fileName"></strong>
                    </div>
                </div>
            </div>

            <div class="meta-section">
                <label class="meta-label">📝 매체 타입</label>
                <div class="media-options" id="mediaOptions">
                    <button class="media-option selected" data-media="online" onclick="selectMedia('online')">
                        📱 온라인
                    </button>
                    <button class="media-option" data-media="print" onclick="selectMedia('print')">
                        📄 인쇄물
                    </button>
                    <button class="media-option" data-media="video" onclick="selectMedia('video')">
                        🎬 영상
                    </button>
                </div>

                <label class="meta-label">💬 제작 맥락 (선택)</label>
                <textarea class="meta-input" id="context" rows="2" placeholder="예: 4월 미식 가이드"></textarea>
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
                <button class="reset-btn" onclick="location.reload()">새로 검수</button>
            </div>

            <div class="score-card">
                <div>종합 점수</div>
                <div class="score-number" id="totalScore">78</div>
            </div>

            <div class="info-card">
                <div class="info-title">📋 평가</div>
                <div class="summary-text" id="summaryContent"></div>
            </div>

            <div class="info-card">
                <div class="info-title">💡 권장사항</div>
                <div class="summary-text" id="recommendationContent"></div>
            </div>
        </div>
    </div>

    <footer>
        © 2024 CatchTable. 브랜드 검수 도구
    </footer>

    <script>
        let selectedFile = null;
        let currentMedia = 'online';

        function selectMedia(media) {
            currentMedia = media;
            document.querySelectorAll('.media-option').forEach(btn => {
                btn.classList.remove('selected');
            });
            event.target.closest('button').classList.add('selected');
        }

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
            if (e.dataTransfer.files.length > 0) {
                handleFile(e.dataTransfer.files[0]);
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

                    console.log('API 호출 시작...');

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

                    console.log('응답 상태:', response.status);

                    const result = await response.json();
                    console.log('결과:', result);

                    if (!response.ok) {
                        throw new Error(result.recommendation || 'API 오류');
                    }

                    showResults(result);
                };
                reader.readAsDataURL(selectedFile);

            } catch (error) {
                console.error('오류:', error);
                alert('오류: ' + error.message);
                btn.innerHTML = '<span>🚀 검수 시작</span>';
                btn.disabled = false;
            }
        });

        function showResults(result) {
            document.getElementById('totalScore').textContent = result.overallScore || 75;
            document.getElementById('summaryContent').textContent = result.recommendation || '검수 완료';

            const improvements = result.improvements ? result.improvements.join('\\n') : '없음';
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
        print("=== API 요청 시작 ===")

        # 요청 데이터 받기
        try:
            data = request.get_json()
            print(f"받은 데이터: {list(data.keys())}")
        except Exception as e:
            print(f"JSON 파싱 에러: {e}")
            return jsonify({
                'overallScore': 50,
                'recommendation': 'JSON 파싱 오류',
                'improvements': []
            }), 400

        image_data = data.get('image', '')
        media_type = data.get('mediaType', 'online')
        context = data.get('context', '')

        print(f"이미지 크기: {len(image_data)}")
        print(f"매체: {media_type}")
        print(f"API 키 있음: {bool(GEMINI_API_KEY)}")

        if not image_data:
            print("이미지 없음")
            return jsonify({
                'overallScore': 0,
                'recommendation': '이미지가 필요합니다',
                'improvements': []
            }), 400

        if not GEMINI_API_KEY:
            print("API 키 없음")
            return jsonify({
                'overallScore': 0,
                'recommendation': 'API 키가 설정되지 않았습니다',
                'improvements': []
            }), 400

        # Base64 처리
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        try:
            image_bytes = base64.b64decode(image_data)
            print(f"Base64 디코딩 성공: {len(image_bytes)} bytes")
        except Exception as e:
            print(f"Base64 디코딩 실패: {e}")
            return jsonify({
                'overallScore': 0,
                'recommendation': 'Base64 디코딩 실패',
                'improvements': []
            }), 400

        # 샘플 응답 (테스트용)
        result = {
            'overallScore': 82,
            'recommendation': f'{media_type} 매체의 브랜드 가이드 검수가 완료되었습니다. 전반적으로 좋은 상태이며, 제시된 개선사항을 반영하면 더욱 우수한 결과를 얻을 수 있습니다.',
            'improvements': [
                '컬러 톤 일관성 유지',
                '타이포그래피 규정 준수',
                '이미지 해상도 개선'
            ]
        }

        return jsonify(result), 200

    except Exception as e:
        print(f"예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'overallScore': 0,
            'recommendation': f'서버 오류: {str(e)}',
            'improvements': []
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'api_key': 'present' if GEMINI_API_KEY else 'missing'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
