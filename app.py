"""
영어 학습 웹앱 (JSON 기반 버전)

- DB(MySQL/PyMySQL)와 OpenAI 의존성 완전 제거
- 문제 데이터: web/data/questions.json (파일이 없으면 인라인 샘플 폴백 1개 사용)
- 채점: 파이썬 내부 비교 (제출된 선택지 인덱스 vs answer)
- 결과 저장: 세션/메모리 전용 (파일·DB 쓰기 없음)
"""
import json
import os
import random
import time

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from functools import wraps

app = Flask(__name__)

# 세션 사용을 위한 secret key 설정
app.secret_key = 'mathweb-json-only-secret-key'

# ---------------------------------------------------------------------------
# 문제 데이터 로딩 레이어 (JSON 기반)
#
# 스키마 계약 (data/questions.json):
# {
#   "categories": [{"id": 1, "name": "단원명", "grade": "초등 5학년"}],
#   "questions": [{
#       "id": 1, "category_id": 1, "type": "objective",
#       "question_text": "...",
#       "choices": ["보기1", "보기2", "보기3", "보기4"],
#       "answer": 1,              # choices의 0-based 인덱스
#       "explanation": "해설"
#   }]
# }
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_JSON_PATH = os.path.join(BASE_DIR, 'data', 'questions.json')

# data/questions.json 이 아직 없을 때만 사용하는 인라인 폴백 샘플 (1개)
_SAMPLE_DATA = {
    "categories": [
        {"id": 1, "name": "Sample Category", "grade": "초등 5학년"}
    ],
    "questions": [
        {
            "id": 1,
            "category_id": 1,
            "type": "objective",
            "question_text": "다음 중 'I go to school every day.'에서 동사를 고르세요.",
            "choices": ["go", "school", "every", "day"],
            "answer": 0,
            "explanation": "'go'가 동사입니다. go는 '매일 학교에 간다'는 동작을 나타내는 동사입니다."
        }
    ]
}

_data_cache = None


def load_data():
    """data/questions.json 을 읽어 전체 데이터를 반환. 없으면 샘플 폴백."""
    global _data_cache
    if _data_cache is not None:
        return _data_cache

    data = None
    if os.path.exists(QUESTIONS_JSON_PATH):
        try:
            with open(QUESTIONS_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"questions.json 로드 실패, 샘플 폴백 사용: {e}")

    if not isinstance(data, dict):
        data = _SAMPLE_DATA

    data.setdefault('categories', [])
    data.setdefault('questions', [])
    _data_cache = data
    return _data_cache


def get_categories():
    """카테고리 목록 반환. 템플릿 호환을 위해 title 키도 함께 제공."""
    result = []
    for c in load_data().get('categories', []):
        item = dict(c)
        item.setdefault('title', c.get('name', ''))
        result.append(item)
    return result


def get_category(category_id):
    for c in get_categories():
        if c['id'] == category_id:
            return c
    return None


def get_questions_by_category(category_id):
    return [q for q in load_data().get('questions', [])
            if q.get('category_id') == category_id]


def get_question(question_id):
    for q in load_data().get('questions', []):
        if q.get('id') == question_id:
            return q
    return None


def grade_objective(question, student_answer):
    """제출된 답(선택지 인덱스 또는 텍스트)을 정답과 비교해 (is_correct, feedback) 반환."""
    choices = question.get('choices', [])
    answer_index = question.get('answer')
    correct_text = ''
    if isinstance(answer_index, int) and 0 <= answer_index < len(choices):
        correct_text = choices[answer_index]

    is_correct = False
    if isinstance(student_answer, int):
        is_correct = student_answer == answer_index
    elif isinstance(student_answer, str):
        if student_answer.strip().isdigit():
            is_correct = int(student_answer.strip()) == answer_index
        else:
            is_correct = student_answer.strip() == correct_text

    explanation = question.get('explanation', '')
    if is_correct:
        feedback = f"정답입니다! {explanation}".strip()
    else:
        feedback = f"아쉽네요! 정답은 '{correct_text}' 입니다. {explanation}".strip()
    return is_correct, feedback


# ---------------------------------------------------------------------------
# 세션/메모리 결과 저장소 (파일·DB 쓰기 없음)
# { user_id: { category_id: {"question_count": n, "correct_count": n, "last_done": ts} } }
# ---------------------------------------------------------------------------
session_results = {}


# 로그인 필요한 페이지에 대한 데코레이터
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def _create_guest_session():
    """게스트용 임시 세션 생성."""
    guest_id = f"guest_{int(time.time())}_{random.randint(1000, 9999)}"
    session['user_id'] = guest_id
    session['name'] = 'Guest User'
    session['type'] = 'student'
    session['level'] = 'Elementary3'  # 기본 난이도
    session['is_guest'] = True


@app.route("/", methods=['GET'])
def index():
    """루트 접속 시 게스트 세션이 없으면 자동 생성 후 바로 학생 화면으로 이동."""
    if 'user_id' not in session:
        _create_guest_session()
        return redirect(url_for('student_dashboard'))
    if session.get('type') == 'student':
        return redirect(url_for('student_dashboard'))
    return render_template('main.html')


#guest
@app.route('/guest-login', methods=['POST'])
def guest_login():
    """게스트 로그인 - 임시 세션 생성"""
    try:
        _create_guest_session()
        return jsonify({
            'success': True,
            'redirect': '/student'
        })
    except Exception as e:
        print(f"Guest login error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/student', methods=['GET'])
@login_required
def student_dashboard():
    if session.get('type') != 'student':
        return redirect(url_for('index'))

    user_name = session.get('name', '사용자')
    is_guest = session.get('is_guest', False)
    student_level = session.get('level', 'Elementary3')

    categories = get_categories()
    if not is_guest:
        categories = [c for c in categories if c.get('grade') == student_level]

    # 세션(메모리) 기반 카테고리별 결과 집계
    user_results = session_results.get(session.get('user_id'), {})
    completed_sessions = 0
    total_score = 0

    for cat in categories:
        status = user_results.get(cat['id'])

        if status:
            question_count = status.get('question_count', 0)
            correct_count = status.get('correct_count', 0)
            score = round((correct_count / question_count) * 100) if question_count > 0 else 0

            cat['done'] = True
            cat['score'] = score
            cat['question_count'] = question_count
            cat['last_done'] = status.get('last_done')

            completed_sessions += 1
            total_score += score
        else:
            cat['done'] = False
            cat['score'] = 0
            cat['question_count'] = 0
            cat['last_done'] = None

    incompleted_sessions = len(categories) - completed_sessions
    average_score = round(total_score / completed_sessions, 1) if completed_sessions > 0 else 0

    return render_template(
        'student.html',
        user_name=user_name,
        categories=categories,
        is_guest=is_guest,
        average_score=average_score,
        completed_sessions=completed_sessions,
        incompleted_sessions=incompleted_sessions
    )


@app.route('/api/student/dashboard', methods=['GET'])
@login_required
def student_dashboard_api():
    if session.get('type') != 'student':
        return jsonify({"error": "unauthorized"}), 403

    is_guest = session.get('is_guest', False)
    student_level = session.get('level', 'Elementary3')

    categories = get_categories()
    if not is_guest:
        categories = [c for c in categories if c.get('grade') == student_level]

    user_results = session_results.get(session.get('user_id'), {})
    completed_sessions = 0
    total_score = 0

    for cat in categories:
        status = user_results.get(cat['id'])

        if status:
            question_count = status.get('question_count', 0)
            correct_count = status.get('correct_count', 0)
            score = round((correct_count / question_count) * 100) if question_count > 0 else 0

            cat['done'] = True
            cat['score'] = score
            cat['question_count'] = question_count
            cat['correct_count'] = correct_count
            cat['last_done'] = status.get('last_done')

            completed_sessions += 1
            total_score += score
        else:
            cat['done'] = False
            cat['score'] = 0
            cat['question_count'] = 0
            cat['correct_count'] = 0
            cat['last_done'] = None

    incompleted_sessions = len(categories) - completed_sessions
    average_score = round(total_score / completed_sessions, 1) if completed_sessions else 0

    return jsonify({
        "stats": {
            "completed_sessions": completed_sessions,
            "incompleted_sessions": incompleted_sessions,
            "average_score": average_score
        },
        "categories": categories
    })


@app.route('/api/student/session/start', methods=['POST'])
@login_required
def start_session():
    """학습 세션 시작 - 메모리에 카테고리별 결과 슬롯 생성 (DB 대체)."""
    if session.get('type') != 'student':
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    category_id = data.get('category_id')

    if get_category(category_id) is None:
        return jsonify({"error": "category_not_found"}), 404

    user_id = session.get('user_id')
    user_results = session_results.setdefault(user_id, {})
    user_results[category_id] = {
        "question_count": 0,
        "correct_count": 0,
        "last_done": time.strftime('%Y-%m-%d %H:%M:%S')
    }

    return jsonify({
        "category_result_id": f"{user_id}:{category_id}"
    })


@app.route('/api/student/category-status', methods=['GET'])
@login_required
def student_category_status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    results = []
    for category_id, status in session_results.get(user_id, {}).items():
        results.append({
            'category_id': category_id,
            'question_count': status.get('question_count', 0),
            'correct_count': status.get('correct_count', 0),
            'last_done': status.get('last_done')
        })
    return jsonify(results)


@app.route('/api/categories/<int:category_id>/questions', methods=['GET'])
def get_category_questions(category_id):
    """카테고리 문제 목록 조회 (JSON 데이터 기반).

    템플릿 호환 필드: question_type('objective'), choices[{number(1-based), text}],
    answer(1-based 번호), hint, explanation.
    """
    if get_category(category_id) is None:
        return jsonify({'error': 'category not found'}), 404

    questions_list = []
    for q in get_questions_by_category(category_id):
        choices = q.get('choices', [])
        answer_index = q.get('answer')
        answer_number = answer_index + 1 if isinstance(answer_index, int) else None

        questions_list.append({
            'id': q.get('id'),
            'category_id': q.get('category_id'),
            'question_type': 'objective',
            'question_text': q.get('question_text', ''),
            'answer': answer_number,
            'hint': q.get('explanation', ''),
            'choices': [{'number': i + 1, 'text': t} for i, t in enumerate(choices)],
            'explanation': q.get('explanation', '')
        })

    return jsonify(questions_list)


@app.route('/api/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    """답 제출 채점 - 파이썬 내부 비교, 결과는 세션/메모리에만 저장."""
    data = request.get_json(silent=True) or {}
    question_id = data.get('question_id')
    student_answer = data.get('student_answer')
    category_id = data.get('category_id')

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({
            'success': False,
            'error': '로그인 정보를 찾을 수 없습니다.'
        }), 401

    question = get_question(question_id)
    if not question:
        return jsonify({
            'success': False,
            'error': '문제를 찾을 수 없습니다.'
        }), 404

    is_correct, feedback = grade_objective(question, student_answer)
    explanation = question.get('explanation', '')

    # 결과 저장은 세션/메모리에만 (파일·DB 쓰기 없음)
    if category_id is not None:
        user_results = session_results.setdefault(user_id, {})
        status = user_results.setdefault(
            category_id,
            {"question_count": 0, "correct_count": 0, "last_done": None}
        )
        status['question_count'] += 1
        if is_correct:
            status['correct_count'] += 1
        status['last_done'] = time.strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'feedback': feedback,
        'explanation': explanation
    })


@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    rows = []
    for c in get_categories():
        rows.append({
            'id': c['id'],
            'name': c.get('name', ''),
            'title': c.get('name', ''),
            'grade': c.get('grade', '')
        })
    return jsonify(rows)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)