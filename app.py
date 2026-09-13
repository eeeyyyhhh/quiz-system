import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime, timedelta
import json
import uuid
import random
from datetime import date, timedelta, datetime
from flask import Flask, render_template, request, jsonify, session, redirect

from config import SUBJECTS, MASTERED_CORRECT_STREAK
from modules.loader import load_all_questions, get_question_id
from modules import db
from modules.ai_helper import generate_explanation

app = Flask(__name__)
app.secret_key = 'study_system_2024_secret'

_practice_store = {}

# ============================================================
# 启动时加载题库
# ============================================================
db.init_db()
ALL_QUESTIONS = load_all_questions()

# ============================================================
# 科目缓存
# ============================================================
_subjects_cache = None
_subjects_cache_time = 0

def _get_subjects_cached():
    global _subjects_cache, _subjects_cache_time
    import time
    now = time.time()
    if _subjects_cache is None or (now - _subjects_cache_time) > 60:
        _subjects_cache = list(SUBJECTS.keys())
        _subjects_cache_time = now
    return _subjects_cache

def get_q_by_id(q_id: str):
    try:
        subject, seq = q_id.split('_', 1)
        for q in ALL_QUESTIONS.get(subject, []):
            if q['seq'] == seq:
                return q
    except Exception:
        pass
    return None

def enrich_question(q: dict) -> dict:
    q_id = get_question_id(q['subject'], q['seq'])
    q['q_id'] = q_id
    q['is_favorite'] = False  # 收藏改为前端本地存储
    q['note'] = db.get_note(q_id)
    exp = db.get_explanation(q_id)
    q['explanation'] = exp.get('content', '')
    q['exp_source'] = exp.get('source', '')
    q['wrong_count'] = 0       # 错题改为前端本地存储
    q['last_wrong_answer'] = ''
    return q

# ============================================================
# 主页
# ============================================================
@app.route('/')
def index():
    subjects = _get_subjects_cached()
    total_questions = sum(len(v) for v in ALL_QUESTIONS.values())
    return render_template('index.html',
        subjects=subjects,
        total_questions=total_questions,
    )

# ============================================================
# 构建题目列表
# ============================================================
def _build_question_list(subject=None, q_type=None, mode='order',
                          range_start=1, range_end=None):
    questions = []
    subjects = [subject] if subject else list(SUBJECTS.keys())
    for sub in subjects:
        qs = ALL_QUESTIONS.get(sub, [])
        for q in qs:
            if q_type and q['type'] != q_type:
                continue
            questions.append(q)

    if range_end:
        questions = [q for q in questions
                     if range_start <= int(q['seq']) <= range_end]

    if mode == 'random':
        random.shuffle(questions)

    return questions

# ============================================================
# 格式化题目
# ============================================================
def _format_question(q: dict, index: int, total: int) -> dict:
    q = dict(q)
    q_id = get_question_id(q['subject'], q['seq'])
    q['q_id']   = q_id
    q['index']  = index
    q['total']  = total
    q['is_favorite'] = False  # 收藏由前端本地判断
    q['note']   = db.get_note(q_id)
    exp = db.get_explanation(q_id)
    q['explanation'] = exp.get('content', '')
    q['exp_source']  = exp.get('source', '')

    options = []
    for key in ['A', 'B', 'C', 'D', 'E', 'F']:
        val = q.get(f'option_{key.lower()}', '')
        if val:
            options.append({'key': key, 'text': val})
    q['options'] = options

    if q['type'] == '判断题':
        q['options'] = [
            {'key': 'A', 'text': '正确'},
            {'key': 'B', 'text': '错误'},
        ]
    return q

# ============================================================
# 练习页面
# ============================================================
@app.route('/practice')
def practice_page():
    subjects = list(SUBJECTS.keys())
    q_types  = ['单选题', '多选题', '判断题']
    return render_template('practice.html', subjects=subjects, q_types=q_types)

@app.route('/api/practice/start', methods=['POST'])
def practice_start():
    data        = request.json
    subject     = data.get('subject') or None
    q_type      = data.get('q_type') or None
    mode        = data.get('mode', 'order')
    range_start = int(data.get('range_start', 1))
    range_end   = int(data.get('range_end')) if data.get('range_end') else None

    questions = _build_question_list(
        subject=subject, q_type=q_type, mode=mode,
        range_start=range_start, range_end=range_end,
    )

    if not questions:
        return jsonify({'error': '没有符合条件的题目'}), 400

    practice_key = str(uuid.uuid4())
    ids = [get_question_id(q['subject'], q['seq']) for q in questions]
    _practice_store[practice_key] = ids
    session['practice_key']   = practice_key
    session['practice_index'] = 0

    return jsonify({
        'total':   len(questions),
        'first_q': _format_question(questions[0], 0, len(questions))
    })

@app.route('/api/practice/start_by_ids', methods=['POST'])
def practice_start_by_ids():
    """前端传入已过滤好的题目ID列表（localStorage模式用）"""
    data  = request.json
    q_ids = data.get('q_ids', [])

    if not q_ids:
        return jsonify({'error': '没有符合条件的题目'}), 400

    questions = [get_q_by_id(qid) for qid in q_ids]
    questions = [q for q in questions if q]

    if not questions:
        return jsonify({'error': '题目数据不存在'}), 400

    practice_key = str(uuid.uuid4())
    ids = [get_question_id(q['subject'], q['seq']) for q in questions]
    _practice_store[practice_key] = ids
    session['practice_key']   = practice_key
    session['practice_index'] = 0

    return jsonify({
        'total':   len(questions),
        'first_q': _format_question(questions[0], 0, len(questions))
    })

@app.route('/api/practice/question/<int:index>')
def practice_question(index):
    practice_key = session.get('practice_key', '')
    ids = _practice_store.get(practice_key, [])

    if not ids or index >= len(ids):
        return jsonify({'error': '题目不存在'}), 404
    q = get_q_by_id(ids[index])
    if not q:
        return jsonify({'error': '题目数据丢失'}), 404
    session['practice_index'] = index
    return jsonify(_format_question(q, index, len(ids)))

@app.route('/api/practice/answer', methods=['POST'])
def practice_answer():
    data        = request.json
    q_id        = data.get('q_id')
    user_answer = data.get('answer', '').upper().strip()

    q = get_q_by_id(q_id)
    if not q:
        return jsonify({'error': '题目不存在'}), 404

    correct_answer = q['answer'].upper().strip()

    if q['type'] == '多选题':
        is_correct = sorted(user_answer) == sorted(correct_answer)
    else:
        is_correct = user_answer == correct_answer

    # 服务器只记录解析相关，不记录个人答题数据
    display_answer = correct_answer
    if q['type'] == '判断题':
        display_answer = '正确' if correct_answer == 'A' else '错误'

    exp = db.get_explanation(q_id)

    return jsonify({
        'correct':        is_correct,
        'correct_answer': display_answer,
        'user_answer':    user_answer,
        'explanation':    exp.get('content', ''),
    })

# ============================================================
# 题目列表接口（供前端过滤用）
# ============================================================
@app.route('/api/local/question_ids')
def api_local_question_ids():
    subject = request.args.get('subject') or None
    q_type  = request.args.get('q_type') or None

    result = []
    subjects = [subject] if subject else list(SUBJECTS.keys())
    for sub in subjects:
        for q in ALL_QUESTIONS.get(sub, []):
            if q_type and q['type'] != q_type:
                continue
            result.append({
                'q_id':    get_question_id(q['subject'], q['seq']),
                'subject': q['subject'],
                'type':    q['type'],
                'seq':     q['seq'],
            })
    return jsonify(result)

# ============================================================
# 科目题目总数接口（首页进度条用）
# ============================================================
@app.route('/api/stats/<subject>')
def api_stats_subject(subject):
    total = len(ALL_QUESTIONS.get(subject, []))
    return jsonify({'total': total, 'answered': 0, 'correct_rate': 0})

# ============================================================
# 错题本页面（改为从本地读取，页面只展示题目内容）
# ============================================================
@app.route('/wrong_book')
def wrong_book_page():
    subjects = list(SUBJECTS.keys())
    return render_template('wrong_book.html', subjects=subjects)

@app.route('/api/wrong_book/questions', methods=['POST'])
def api_wrong_book_questions():
    """前端传入错题ID列表，返回题目详情"""
    data    = request.json
    q_ids   = data.get('q_ids', [])
    subject = data.get('subject', '')

    result = []
    for q_id in q_ids:
        q = get_q_by_id(q_id)
        if not q:
            continue
        if subject and q['subject'] != subject:
            continue
        item = dict(q)
        item['q_id'] = q_id

        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})
        item['options'] = options

        if q['type'] == '判断题':
            item['options'] = [
                {'key': 'A', 'text': '正确'},
                {'key': 'B', 'text': '错误'},
            ]
            item['correct_answer_display'] = '正确' if q['answer'] == 'A' else '错误'
        else:
            item['correct_answer_display'] = q['answer']

        exp = db.get_explanation(q_id)
        item['explanation'] = exp.get('content', '')
        result.append(item)

    return jsonify(result)

@app.route('/api/wrong_book/remove/<q_id>', methods=['POST'])
def api_remove_wrong(q_id):
    return jsonify({'success': True})

# ============================================================
# 考试模式
# ============================================================
@app.route('/exam')
def exam_page():
    subjects = list(SUBJECTS.keys())
    return render_template('exam.html', subjects=subjects)

@app.route('/api/exam/start', methods=['POST'])
def exam_start():
    data     = request.json
    subject  = data.get('subject') or None
    total    = int(data.get('total', 100))
    duration = int(data.get('duration', 60))
    ratio    = data.get('ratio', {})

    all_qs = _build_question_list(subject=subject, mode='random')
    if not all_qs:
        return jsonify({'error': '题库为空'}), 400

    selected = []
    type_map = {}
    for q in all_qs:
        type_map.setdefault(q['type'], []).append(q)

    if ratio:
        for q_type, count in ratio.items():
            pool = type_map.get(q_type, [])
            random.shuffle(pool)
            selected += pool[:min(count, len(pool))]
    else:
        random.shuffle(all_qs)
        selected = all_qs[:total]

    random.shuffle(selected)
    selected = selected[:total]

    exam_key = str(uuid.uuid4())
    exam_ids = [get_question_id(q['subject'], q['seq']) for q in selected]
    _practice_store[exam_key] = exam_ids
    session['exam_key']      = exam_key
    session['exam_duration'] = duration * 60
    session['exam_subject']  = subject or '综合'

    formatted = [_format_question(q, i, len(selected)) for i, q in enumerate(selected)]
    for q in formatted:
        q.pop('answer', None)

    return jsonify({
        'total':     len(selected),
        'duration':  duration * 60,
        'questions': formatted,
    })

@app.route('/api/exam/submit', methods=['POST'])
def exam_submit():
    data     = request.json
    answers  = data.get('answers', {})
    duration = int(data.get('duration', 0))

    exam_key = session.get('exam_key', '')
    ids = _practice_store.get(exam_key, [])
    if not ids:
        return jsonify({'error': '考试会话已过期'}), 400

    total   = len(ids)
    correct = 0
    details = []

    for q_id in ids:
        q = get_q_by_id(q_id)
        if not q:
            continue
        user_answer    = answers.get(q_id, '').upper().strip()
        correct_answer = q['answer'].upper().strip()

        if q['type'] == '多选题':
            is_correct = sorted(user_answer) == sorted(correct_answer)
        else:
            is_correct = user_answer == correct_answer

        if is_correct:
            correct += 1

        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})

        display_correct = correct_answer
        display_user    = user_answer
        if q['type'] == '判断题':
            display_correct = '正确' if correct_answer == 'A' else '错误'
            display_user    = '正确' if user_answer == 'A' else (
                              '错误' if user_answer == 'B' else '未作答')

        exp = db.get_explanation(q_id)
        details.append({
            'q_id':           q_id,
            'stem':           q['stem'],
            'type':           q['type'],
            'options':        options,
            'correct_answer': display_correct,
            'user_answer':    display_user,
            'is_correct':     is_correct,
            'explanation':    exp.get('content', ''),
        })

    score         = round(correct / total * 100, 1) if total else 0
    subject_label = session.get('exam_subject', '综合')

    db.save_exam_record(
        subject_label, total, correct, score, duration,
        json.dumps(details, ensure_ascii=False)
    )

    return jsonify({
        'total':    total,
        'correct':  correct,
        'score':    score,
        'duration': duration,
        'details':  details,
    })

# ============================================================
# 收藏 / 笔记 / 解析
# ============================================================
@app.route('/api/favorite', methods=['POST'])
def api_favorite():
    # 收藏已改为前端本地存储，此接口保留兼容
    return jsonify({'favorited': False})

@app.route('/api/note', methods=['POST'])
def api_note():
    data    = request.json
    q_id    = data.get('q_id')
    content = data.get('content', '')
    db.save_note(q_id, content)
    return jsonify({'ok': True})

@app.route('/api/explanation', methods=['POST'])
def api_explanation():
    data    = request.json
    q_id    = data.get('q_id')
    content = data.get('content', '')
    source  = data.get('source', 'manual')
    db.save_explanation(q_id, content, source)
    return jsonify({'ok': True})

@app.route('/api/explanation/ai', methods=['POST'])
def api_ai_explanation():
    data = request.json
    q_id = data.get('q_id')
    q    = get_q_by_id(q_id)
    if not q:
        return jsonify({'error': '题目不存在'}), 404
    content = generate_explanation(q)
    db.save_explanation(q_id, content, 'ai')
    return jsonify({'content': content})

# ============================================================
# 统计页
# ============================================================
@app.route('/stats')
def stats_page():
    subjects = list(SUBJECTS.keys())
    subject_totals = {}
    for sub in subjects:
        subject_totals[sub] = len(ALL_QUESTIONS.get(sub, []))
    total_questions = sum(subject_totals.values())
    exam_records = db.get_exam_records(10)
    return render_template('stats.html',
        subjects=subjects,
        subject_totals=subject_totals,
        total_questions=total_questions,
        exam_records=exam_records,
    )

# ============================================================
# 学习计划
# ============================================================
@app.route('/plan')
def plan_page():
    plan            = db.get_plan()
    subjects        = list(SUBJECTS.keys())
    total_questions = sum(len(v) for v in ALL_QUESTIONS.values())
    return render_template('plan.html',
        plan=plan,
        subjects=subjects,
        total_questions=total_questions,
    )

@app.route('/api/plan', methods=['POST'])
def api_plan():
    data          = request.json
    exam_date     = data.get('exam_date')
    total_target  = int(data.get('total_target', 0))
    daily_target  = int(data.get('daily_target', 0))
    focus_subject = data.get('focus_subject', '')
    db.save_plan(exam_date, total_target, daily_target, focus_subject)
    return jsonify({'ok': True})

@app.route('/plan/save', methods=['POST'])
def plan_save():
    exam_date     = request.form.get('exam_date', '')
    daily_target  = int(request.form.get('daily_target', 50))
    focus_subject = request.form.get('focus_subject', '')
    total_target  = daily_target * 30
    db.save_plan(exam_date, total_target, daily_target, focus_subject)
    return redirect('/plan')

# ============================================================
# 今日复习
# ============================================================
@app.route('/review')
def review_page():
    return render_template('review.html')

@app.route('/api/today_review')
def api_today_review():
    # 复习题目由前端本地决定，此接口返回空
    return jsonify({'total': 0, 'questions': []})

# ============================================================
# 启动
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("  📚 电力刷题系统启动中...")
    print(f"  访问地址：http://localhost:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)