"""
Brand Guide Review Tool - Flask Backend API
캐치테이블 브랜드 가이드 검수 자동화 도구 백엔드
"""

import os
import json
import base64
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from werkzeug.utils import secure_filename

# Flask 앱 초기화
app = Flask(__name__)
CORS(app)

# 설정
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Gemini API 초기화
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY 환경변수를 설정해주세요")

genai.configure(api_key=GEMINI_API_KEY)

# 평가 기준표
EVALUATION_CRITERIA = {
    'online': [
        {'id': 'tone', 'label': '톤 & 매너', 'weight': 20},
        {'id': 'photography', 'label': '사진 퀄리티', 'weight': 20},
        {'id': 'typography', 'label': '타이포그래피', 'weight': 15},
        {'id': 'color', 'label': '컬러 사용', 'weight': 15},
        {'id': 'graphics', 'label': '그래픽 에셋', 'weight': 15},
        {'id': 'copywriting', 'label': '카피라이팅', 'weight': 15},
    ],
    'print': [
        {'id': 'tone', 'label': '톤 & 매너', 'weight': 20},
        {'id': 'photography', 'label': '사진 퀄리티', 'weight': 18},
        {'id': 'typography', 'label': '타이포그래피', 'weight': 16},
        {'id': 'color', 'label': '컬러 사용 (CMYK)', 'weight': 16},
        {'id': 'graphics', 'label': '그래픽 에셋', 'weight': 15},
        {'id': 'copywriting', 'label': '카피라이팅', 'weight': 15},
    ],
    'video': [
        {'id': 'tone', 'label': '톤 & 매너', 'weight': 20},
        {'id': 'framing', 'label': '프레임 구성', 'weight': 20},
        {'id': 'subtitle', 'label': '자막 & 텍스트', 'weight': 15},
        {'id': 'color', 'label': '컬러 사용', 'weight': 15},
        {'id': 'graphics', 'label': '그래픽 에셋', 'weight': 15},
        {'id': 'narration', 'label': '나레이션/자막', 'weight': 15},
    ]
}

# T&M 가이드 평가 프롬프트
EVALUATION_PROMPTS = {
    'online': """
당신은 캐치테이블의 브랜드 가이드 검수 전문가입니다.
제공된 온라인 콘텐츠(SNS, 웹사이트, 이메일)를 다음 기준에 따라 평가해주세요:

[평가 항목]

1. 톤 & 매너 (20%): 명료함, 감각성, 고유성이 드러나는가?
   - 자연광, 소프트 라이팅, 집중된 구성, 여백이 있는가?
   - 해당 없음: 텍스트만 있고 이미지/그래픽이 없는 경우 "pass"로 표시

2. 사진 퀄리티 (20%): 사진의 품질이 우수한가?
   - 해상도, 초점, 노출, 색감이 적절한가?
   - 해당 없음: 사진이 없으면 "pass"로 표시

3. 타이포그래피 (15%): 타입 선택과 배치가 브랜드답는가?
   - 서체 선택, 크기, 간격, 위계가 명확한가?

4. 컬러 사용 (15%): 캐치테이블 브랜드 컬러가 적절히 사용되었는가?
   - 오렌지(#EA580C), 따뜻한 톤(#FF3000), 네이비(#003963) 활용

5. 그래픽 에셋 (15%): 그래픽 요소가 브랜드다운가?
   - 모노라인, 단순한 형태, 위트있는 표현
   - 해당 없음: 그래픽이 없으면 "pass"로 표시

6. 카피라이팅 (15%): 텍스트 메시지가 브랜드 성격을 반영하는가?
   - 명확성, 설득력, 감정적 연결
   - 해당 없음: 텍스트가 없으면 "pass"로 표시

[응답 형식]

반드시 다음 JSON 형식으로 정확하게 응답해주세요. 점수는 0-100 또는 "pass"입니다:

{
  "criteria": [
    {
      "id": "tone",
      "label": "톤 & 매너",
      "weight": 20,
      "score": 85,
      "verdict": "적합",
      "reasoning": "브랜드 톤이 명확하게 표현되었습니다. 자연광과 breathing space가 잘 적용되었습니다.",
      "suggestion": "더 강렬한 감각적 요소를 추가하면 차별화가 높아질 것입니다."
    },
    ...
  ],
  "actionItems": [
    {
      "priority": "high",
      "criteriaId": "color",
      "criteriaLabel": "컬러 사용",
      "recommendation": "브랜드 오렌지를 더 적극적으로 활용하면 시인성이 높아질 것입니다."
    }
  ],
  "summary": "전체 평가 요약: 브랜드 톤은 잘 표현되었으나 컬러 활용 개선이 필요합니다.",
  "overallVerdictScore": 78,
  "worstOfScore": 72
}

주의사항:
- 평가 불가 항목은 score를 "pass"로 설정
- verdict는 "적합", "주의", "부적합" 중 하나
- actionItems는 최대 5개, priority는 "high", "medium", "low" 중 하나
- summary는 1-2문장의 요약
- worstOfScore는 pass가 아닌 항목 중 가장 낮은 점수
""",
    'print': """
당신은 캐치테이블의 브랜드 가이드 검수 전문가입니다.
제공된 인쇄물(포스터, 브로셔, 명함)을 다음 기준에 따라 평가해주세요:

[평가 항목]

1. 톤 & 매너 (20%): 인쇄물이 브랜드 톤을 잘 표현하는가?
   - 시각적 일관성, 감각성, 명료함

2. 사진 퀄리티 (18%): 사진의 인쇄 품질이 우수한가?
   - 해상도(300dpi 이상), 색감 정확성, 선명도
   - 해당 없음: 사진이 없으면 "pass"로 표시

3. 타이포그래피 (16%): 인쇄 타입이 적절한가?
   - 가독성, 계층 구조, 인쇄 환경에 맞는 크기

4. 컬러 사용 - CMYK (16%): CMYK 컬러 변환이 적절한가?
   - 오렌지, 따뜻한 톤, 네이비의 CMYK 표현

5. 그래픽 에셋 (15%): 인쇄물에 사용된 그래픽이 브랜드다운가?
   - 일관성, 단순성, 인쇄 적합성
   - 해당 없음: 그래픽이 없으면 "pass"로 표시

6. 카피라이팅 (15%): 텍스트가 명확하고 설득력 있는가?
   - 가독성, 메시지 명확성, 브랜드 톤 일치
   - 해당 없음: 텍스트가 없으면 "pass"로 표시

[응답 형식]

반드시 다음 JSON 형식으로 정확하게 응답해주세요:

{
  "criteria": [
    {
      "id": "tone",
      "label": "톤 & 매너",
      "weight": 20,
      "score": 85,
      "verdict": "적합",
      "reasoning": "인쇄 매체에 적합한 톤이 잘 표현되었습니다.",
      "suggestion": "여백 활용을 더 극대화하면 고급스러움이 증가할 것입니다."
    },
    ...
  ],
  "actionItems": [
    {
      "priority": "high",
      "criteriaId": "color",
      "criteriaLabel": "컬러 사용 (CMYK)",
      "recommendation": "CMYK 색상값의 정확도를 더 높이시기 바랍니다."
    }
  ],
  "summary": "전체 평가 요약: 인쇄 품질은 양호하나 색상 관리 개선이 필요합니다.",
  "overallVerdictScore": 81,
  "worstOfScore": 76
}
""",
    'video': """
당신은 캐치테이블의 브랜드 가이드 검수 전문가입니다.
제공된 영상 프레임(유튜브, TikTok, 광고 영상)을 다음 기준에 따라 평가해주세요:

[평가 항목]

1. 톤 & 매너 (20%): 영상의 전체적인 톤이 브랜드다운가?
   - 감정, 속도감, 분위기

2. 프레임 구성 (20%): 구성과 시각적 배치가 우수한가?
   - 카메라 앵글, 움직임, 시각적 계층

3. 자막 & 텍스트 (15%): 자막과 오버레이 텍스트가 적절한가?
   - 가독성, 타이포그래피, 배치
   - 해당 없음: 자막이 없으면 "pass"로 표시

4. 컬러 사용 (15%): 색감이 브랜드 아이덴티티와 일치하는가?
   - 컬러 그레이딩, 일관성, 감정 표현

5. 그래픽 에셋 (15%): 그래픽 요소가 브랜드다운가?
   - 애니메이션, 트랜지션, 이펙트의 적절성
   - 해당 없음: 그래픽이 없으면 "pass"로 표시

6. 나레이션/자막 (15%): 음성 표현이 브랜드 톤과 맞는가?
   - 목소리, 속도, 발음, 감정 표현
   - 해당 없음: 나레이션이 없으면 "pass"로 표시

[응답 형식]

반드시 다음 JSON 형식으로 정확하게 응답해주세요:

{
  "criteria": [
    {
      "id": "tone",
      "label": "톤 & 매너",
      "weight": 20,
      "score": 78,
      "verdict": "주의",
      "reasoning": "영상에서 브랜드 톤이 표현되었으나 일관성이 다소 떨어집니다.",
      "suggestion": "더 강렬한 감정적 표현을 추가하면 임팩트가 증가할 것입니다."
    },
    ...
  ],
  "actionItems": [
    {
      "priority": "high",
      "criteriaId": "color",
      "criteriaLabel": "컬러 사용",
      "recommendation": "브랜드 오렌지를 강조하는 색감 그레이딩을 적용해주세요."
    }
  ],
  "summary": "전체 평가 요약: 구성은 양호하나 톤 일관성과 색감 강화가 필요합니다.",
  "overallVerdictScore": 76,
  "worstOfScore": 72
}
"""
}

def allowed_file(filename):
    """파일 확장자 확인"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_total_score(criteria_results):
    """가중치 기반 총점 계산 (pass 제외)"""
    total_score = 0
    total_weight = 0

    for criterion in criteria_results:
        # pass는 제외
        if isinstance(criterion['score'], (int, float)):
            weighted_score = (criterion['score'] * criterion['weight']) / 100
            total_score += weighted_score
            total_weight += criterion['weight']

    # 가중치를 정규화해서 총점 계산
    if total_weight > 0:
        total_score = (total_score / total_weight) * 100

    return round(total_score, 1)

def encode_image_to_base64(file_path):
    """이미지를 Base64로 인코딩"""
    with open(file_path, 'rb') as image_file:
        return base64.standard_b64encode(image_file.read()).decode('utf-8')

def analyze_with_gemini(image_paths, media_type, context=''):
    """Gemini Vision API를 사용한 이미지 분석"""
    try:
        # 이미지 데이터 준비
        image_parts = []
        for image_path in image_paths:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")

            # Gemini API용 이미지 데이터
            image_data = {
                "mime_type": "image/jpeg",
                "data": encode_image_to_base64(image_path)
            }
            image_parts.append(image_data)

        # 모델 선택 및 평가 실행
        model = genai.GenerativeModel('gemini-1.5-flash')

        # 프롬프트 구성
        prompt = EVALUATION_PROMPTS.get(media_type, EVALUATION_PROMPTS['online'])

        # 맥락정보 추가
        if context:
            prompt += f"\n\n[제작 맥락]\n{context}\n\n위의 제작 맥락을 고려하여 평가를 수행해주세요."

        # 이미지와 프롬프트를 함께 전달
        content = [prompt]
        for image_data in image_parts:
            content.append(image_data)

        response = model.generate_content(content)
        response_text = response.text

        # JSON 응답 파싱
        # JSON 부분 추출 (```json ... ``` 형식 처리)
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1

        if json_start == -1 or json_end == 0:
            raise ValueError("응답에서 JSON을 찾을 수 없습니다")

        json_str = response_text[json_start:json_end]
        result = json.loads(json_str)

        return result

    except Exception as e:
        print(f"Gemini API 오류: {str(e)}")
        raise

@app.route('/health', methods=['GET'])
def health_check():
    """헬스 체크 엔드포인트"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/api/brand-check', methods=['POST'])
def brand_check():
    """
    브랜드 가이드 검수 API

    Request:
    - files: 이미지 파일들 (multipart/form-data)
    - mediaType: 'online' | 'print' | 'video'
    - context: 제작 맥락 (선택사항) - "4월 미식 가이드 세로형 배너"

    Response:
    - reviewId: 검수 ID
    - totalScore: 총점 (0-100)
    - worstOfScore: 최종 판정 점수 (가장 낮은 항목)
    - mediaType: 매체 타입
    - criteria: 항목별 평가 결과
    - summary: 전체 평가 요약
    - actionItems: 최우선 권장사항 TOP 3
    """
    try:
        # 입력 검증
        if 'files' not in request.files or len(request.files.getlist('files')) == 0:
            return jsonify({
                'error': '이미지 파일이 필요합니다',
                'code': 'NO_FILES'
            }), 400

        media_type = request.form.get('mediaType', 'online')
        context = request.form.get('context', '')  # 맥락정보
        if media_type not in EVALUATION_CRITERIA:
            return jsonify({
                'error': '유효하지 않은 매체 타입입니다',
                'code': 'INVALID_MEDIA_TYPE'
            }), 400

        # 파일 저장
        uploaded_files = request.files.getlist('files')
        saved_paths = []

        for file in uploaded_files:
            if file.filename == '':
                continue

            if not allowed_file(file.filename):
                return jsonify({
                    'error': f"지원하지 않는 파일 형식입니다: {file.filename}",
                    'code': 'UNSUPPORTED_FORMAT'
                }), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            saved_paths.append(filepath)

        if not saved_paths:
            return jsonify({
                'error': '저장된 파일이 없습니다',
                'code': 'NO_SAVED_FILES'
            }), 400

        # Gemini API로 분석
        analysis_result = analyze_with_gemini(saved_paths, media_type, context)

        # 응답 형식 표준화
        criteria_results = analysis_result.get('criteria', [])

        # 기본 기준표 구조와 병합
        default_criteria = EVALUATION_CRITERIA[media_type]
        for default_criterion in default_criteria:
            matching = next(
                (c for c in criteria_results if c['id'] == default_criterion['id']),
                None
            )
            if matching:
                matching['weight'] = default_criterion['weight']
            else:
                criteria_results.append({
                    'id': default_criterion['id'],
                    'label': default_criterion['label'],
                    'weight': default_criterion['weight'],
                    'score': 'pass',
                    'verdict': '평가 불가',
                    'reasoning': '평가 항목이 해당 콘텐츠에 없습니다.',
                    'suggestion': '해당 없음'
                })

        # 총점 계산 (pass 제외)
        total_score = calculate_total_score(criteria_results)

        # worstOfScore 계산 (pass가 아닌 항목 중 가장 낮은 점수)
        worst_of_score = 100
        for criterion in criteria_results:
            if isinstance(criterion['score'], (int, float)):
                worst_of_score = min(worst_of_score, criterion['score'])

        if worst_of_score == 100:
            worst_of_score = total_score  # 모든 항목이 pass인 경우

        # 최우선 수정 권장사항 TOP 3 추출
        action_items = analysis_result.get('actionItems', [])
        top_3_actions = sorted(
            action_items,
            key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x.get('priority', 'low'), 2)
        )[:3]

        # 응답 생성
        response = {
            'reviewId': datetime.now().strftime('%Y%m%d%H%M%S'),
            'status': 'completed',
            'totalScore': total_score,
            'worstOfScore': worst_of_score,
            'mediaType': media_type,
            'timestamp': datetime.now().isoformat(),
            'criteria': criteria_results,
            'summary': analysis_result.get('summary', '분석이 완료되었습니다.'),
            'actionItems': top_3_actions,  # TOP 3만 반환
            'allActionItems': action_items  # 전체도 포함 (참고용)
        }

        return jsonify(response), 200

    except FileNotFoundError as e:
        return jsonify({
            'error': str(e),
            'code': 'FILE_NOT_FOUND'
        }), 400
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'AI 응답을 파싱할 수 없습니다',
            'code': 'PARSE_ERROR'
        }), 500
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        return jsonify({
            'error': str(e),
            'code': 'INTERNAL_ERROR'
        }), 500

@app.errorhandler(413)
def too_large(e):
    """파일 크기 초과 오류"""
    return jsonify({
        'error': f'파일이 너무 큽니다. 최대 {MAX_FILE_SIZE / 1024 / 1024}MB입니다.',
        'code': 'FILE_TOO_LARGE'
    }), 413

if __name__ == '__main__':
    # 포트는 환경변수에서 (배포 환경 대응)
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
