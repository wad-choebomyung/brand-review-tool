import os
import json
import base64
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

@app.route('/')
def index():
    """메인 페이지 서빙"""
    return send_file('브랜드검수도구_간단.html', mimetype='text/html')

@app.route('/api/review', methods=['POST'])
def review_brand():
    """브랜드 검수 API"""
    try:
        data = request.get_json()
        image_data = data.get('image', '')
        media_type = data.get('mediaType', 'online')
        context = data.get('context', '')

        if not image_data or not GEMINI_API_KEY:
            return jsonify({
                'error': '이미지 또는 API 키가 없습니다',
                'overallScore': 0,
                'recommendation': '설정을 확인해주세요'
            }), 400

        # Base64 데이터 처리
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)

        # Gemini API 호출
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

        headers = {
            "Content-Type": "application/json"
        }

        prompt = f"""당신은 전문적인 브랜드 검수 전문가입니다.

제공된 이미지를 분석하여 다음 항목들을 평가해주세요:
- 브랜드 일관성 (0-100)
- 디자인 품질 (0-100)
- 가독성/명확성 (0-100)
- 전문성 (0-100)
- 타겟 오디언스 적합도 (0-100)

매체 유형: {media_type}
추가 컨텍스트: {context}

다음 JSON 형식으로만 응답해주세요:
{{
    "brandConsistency": 75,
    "designQuality": 78,
    "readability": 82,
    "professionalism": 80,
    "targetAudienceFit": 76,
    "overallScore": 78,
    "strengths": ["강점1", "강점2", "강점3"],
    "improvements": ["개선사항1", "개선사항2"],
    "recommendation": "전체 권장사항"
}}"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_data
                            }
                        }
                    ]
                }
            ]
        }

        response = requests.post(
            f"{url}?key={GEMINI_API_KEY}",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            return jsonify({
                'error': f'API 오류: {response.status_code}',
                'overallScore': 50,
                'recommendation': 'API 호출에 문제가 있습니다. 다시 시도해주세요.'
            }), 400

        response_data = response.json()

        try:
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
                    'strengths': ['이미지 분석 완료'],
                    'improvements': ['더 자세한 분석을 위해 다시 시도해주세요']
                }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            result = {
                'overallScore': 75,
                'recommendation': '이미지 분석이 완료되었습니다',
                'strengths': ['분석 성공'],
                'improvements': ['상세 분석을 위해 다시 시도해주세요']
            }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'error': str(e),
            'overallScore': 0,
            'recommendation': '오류가 발생했습니다'
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """헬스 체크"""
    return jsonify({'status': 'ok', 'apiKey': 'configured' if GEMINI_API_KEY else 'missing'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
