# ─────────────────────────────────────────────────────────
#  나라면? 웹앱 - 메인 서버 파일
#  Flask로 만든 AI 기반 관계/답변 예측 웹앱
# ─────────────────────────────────────────────────────────

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import json
import os
import anthropic
from dotenv import load_dotenv

# .env 파일에서 ANTHROPIC_API_KEY 등 환경변수 불러오기
load_dotenv()

app = Flask(__name__)
# 세션 암호화에 사용하는 키 (반드시 설정해야 session이 동작함)
app.secret_key = os.getenv('SECRET_KEY', 'fallback-dev-key')

@app.template_filter('iramyeon')
def iramyeon_filter(name):
    if not name:
        return '이라면'
    code = ord(name[-1]) - 0xAC00
    return '이라면' if 0 <= code <= 11171 and code % 28 != 0 else '라면'

# 프로필 데이터를 저장할 JSON 파일 경로
PROFILE_FILE = 'user_profile.json'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ──────────────────────────────
# 헬퍼 함수: 프로필 읽기/쓰기
# ──────────────────────────────

def load_profile():
    """저장된 프로필 파일을 읽어 딕셔너리로 반환. 없으면 None."""
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_profile(profile):
    """프로필 딕셔너리를 JSON 파일로 저장."""
    with open(PROFILE_FILE, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def parse_relationship_response(text):
    """Claude 응답 텍스트를 파싱해서 딕셔너리로 반환."""
    result = {
        'relationship': '알 수 없음',
        'score': 50,
        'one_liner': '',
        'reason': ''
    }
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('관계유형:'):
            result['relationship'] = line.replace('관계유형:', '').strip()
        elif line.startswith('궁합점수:'):
            try:
                nums = ''.join(c for c in line if c.isdigit())
                result['score'] = min(100, max(0, int(nums)))
            except Exception:
                result['score'] = 50
        elif line.startswith('한줄평:'):
            result['one_liner'] = line.replace('한줄평:', '').strip()
        elif line.startswith('이유:'):
            result['reason'] = line.replace('이유:', '').strip()
    return result


# ──────────────────────────────
# 페이지 라우트
# ──────────────────────────────

@app.route('/')
def index():
    """메인 홈 화면 - 두 가지 기능 카드를 보여줌"""
    profile = load_profile()
    profile_name  = profile.get('name',  '나')  if profile else '나'
    profile_photo = profile.get('photo') if profile else None
    return render_template('index.html',
                           profile_exists=profile is not None,
                           profile_name=profile_name,
                           profile_photo=profile_photo)


@app.route('/setup/login', methods=['GET', 'POST'])
def setup_login():
    """셋업 로그인 페이지 - 비밀번호 확인 후 셋업 페이지 접근 허용"""
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == os.getenv('SETUP_PASSWORD', '1234'):
            session['setup_auth'] = True  # 세션에 인증 완료 표시
            return redirect(url_for('setup'))
        return render_template('setup_login.html', error='비밀번호가 틀렸어요 🔒')
    return render_template('setup_login.html', error=None)


@app.route('/setup/logout')
def setup_logout():
    """셋업 로그아웃 - 세션 삭제 후 홈으로 이동"""
    session.pop('setup_auth', None)
    return redirect(url_for('index'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """셋업 페이지 - 앱 주인이 자신의 정보를 입력하고 저장하는 페이지"""
    # 세션에 인증 정보가 없으면 로그인 페이지로 이동
    if not session.get('setup_auth'):
        return redirect(url_for('setup_login'))

    if request.method == 'POST':
        existing = load_profile()
        profile = {
            'name': request.form.get('name', '나').strip(),
            'personality': request.form.getlist('personality'),
            'speaking_style': request.form.get('speaking_style', ''),
            'values': request.form.getlist('values'),
            'extra_info': request.form.get('extra_info', '').strip(),
            'photo': existing.get('photo') if existing else None
        }
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            ext = photo_file.filename.rsplit('.', 1)[1].lower()
            filename = f'profile_photo.{ext}'
            photo_file.save(os.path.join(UPLOAD_FOLDER, filename))
            profile['photo'] = filename
        save_profile(profile)
        return jsonify({'success': True})

    # GET 요청: 기존 프로필이 있으면 불러와서 미리 채워줌
    profile = load_profile()
    return render_template('setup.html', profile=profile)


@app.route('/relationship')
def relationship():
    """관계 예측기 페이지"""
    profile = load_profile()
    if not profile:
        # 프로필 미설정 시 셋업 페이지로 이동
        return redirect(url_for('setup'))
    return render_template('relationship.html',
                           profile_name=profile.get('name', '나'),
                           profile_photo=profile.get('photo'))


@app.route('/answer')
def answer():
    """내 답변 예측기 페이지"""
    profile = load_profile()
    if not profile:
        return redirect(url_for('setup'))
    return render_template('answer.html',
                           profile_name=profile.get('name', '나'),
                           profile_photo=profile.get('photo'))


# ──────────────────────────────
# API 엔드포인트 (AJAX 요청 처리)
# ──────────────────────────────

@app.route('/api/predict-relationship', methods=['POST'])
def predict_relationship():
    """
    방문자의 성격 태그를 받아 Claude AI로 관계 유형을 예측.
    요청 body: { "personality": ["외향적인", "유머러스한", ...] }
    """
    data = request.get_json()
    visitor_personality = data.get('personality', [])
    visitor_appearance  = data.get('appearance',  [])
    visitor_hobbies     = data.get('hobbies',     [])
    visitor_fashion     = data.get('fashion',     [])
    visitor_animal      = data.get('animal',      '')
    visitor_gender      = data.get('gender',      '')

    if not visitor_personality and not visitor_appearance and not visitor_hobbies and not visitor_fashion and not visitor_animal:
        return jsonify({'error': '하나 이상 선택해주세요.'}), 400

    profile = load_profile()
    if not profile:
        return jsonify({'error': '프로필이 설정되지 않았습니다.'}), 400

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    extra = f"\n- 추가 정보: {profile['extra_info']}" if profile.get('extra_info') else ''
    personality_str = ', '.join(visitor_personality) if visitor_personality else '정보 없음'
    appearance_str  = ', '.join(visitor_appearance)  if visitor_appearance  else '정보 없음'
    hobbies_str     = ', '.join(visitor_hobbies)     if visitor_hobbies     else '정보 없음'
    fashion_str     = ', '.join(visitor_fashion)     if visitor_fashion     else '정보 없음'
    animal_str      = visitor_animal if visitor_animal else '정보 없음'
    gender_str      = f"\n- 성별: {visitor_gender}"  if visitor_gender      else ''

    if visitor_gender == '남자':
        rel_options = '절친 / 썸 / 그냥 아는 사이 / 남남 / 동료 / 가족 같은 친구 / 남자친구(애인)'
    else:
        rel_options = '절친 / 그냥 아는 사이 / 남남 / 동료 / 가족 같은 친구'

    prompt = f"""당신은 사람 간의 관계와 궁합을 분석하는 전문가입니다.

[{profile['name']}에 대한 정보]
- 성격: {', '.join(profile['personality'])}
- 말투: {profile['speaking_style']}
- 가치관: {', '.join(profile['values'])}{extra}

[상대방의 정보]{gender_str}
- 성격: {personality_str}
- 외모 스타일: {appearance_str}
- 눈매/동물상: {animal_str}
- 패션 스타일: {fashion_str}
- 취미: {hobbies_str}

두 사람의 성격, 외모, 취미, 패션 스타일 등을 종합적으로 분석해서 어떤 관계가 될지 예측해주세요.

반드시 아래 형식으로만 답변하세요 (다른 말은 쓰지 마세요):
관계유형: [{rel_options} 중 하나만]
궁합점수: [0~100 숫자만]
한줄평: [재미있고 공감 가는 한 문장]
이유: [두 사람의 관계를 2~3문장으로 설명]"""

    try:
        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}]
        )
        result = parse_relationship_response(message.content[0].text.strip())
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': f'AI 예측 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/predict-answer', methods=['POST'])
def predict_answer():
    """
    방문자의 질문/상담 내용을 받아 Claude AI로 프로필 주인의 예상 답변을 생성.
    요청 body: { "question": "요즘 힘든 일이 있는데..." }
    """
    data = request.get_json()
    question = data.get('question', '').strip()

    if not question:
        return jsonify({'error': '내용을 입력해주세요.'}), 400

    profile = load_profile()
    if not profile:
        return jsonify({'error': '프로필이 설정되지 않았습니다.'}), 400

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    extra = f"\n- 추가 정보: {profile['extra_info']}" if profile.get('extra_info') else ''
    prompt = f"""지금부터 당신은 '{profile['name']}'입니다.
아래는 당신('{profile['name']}') 자신에 대한 설명입니다.

[나({profile['name']})에 대한 정보]
- 성격: {', '.join(profile['personality'])}
- 말투: {profile['speaking_style']}
- 가치관: {', '.join(profile['values'])}{extra}

누군가 나에게 이런 말/질문을 했습니다:
"{question}"

나의 성격, 말투, 가치관을 완벽히 반영해서 내가 실제로 할 것 같은 자연스러운 답변만 작성해주세요.
설명이나 부연 없이 답변 내용만 써주세요."""

    try:
        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({'answer': message.content[0].text.strip()})

    except Exception as e:
        return jsonify({'error': f'AI 예측 중 오류가 발생했습니다: {str(e)}'}), 500


# ──────────────────────────────
# 서버 실행
# ──────────────────────────────

if __name__ == '__main__':
    # debug=True: 코드 변경 시 자동 재시작 (개발용)
    # host='0.0.0.0': 같은 네트워크의 다른 기기에서도 접속 가능
    print('나라면? 서버 시작! http://localhost:5000')
    app.run(debug=True, host='0.0.0.0', port=5000)
