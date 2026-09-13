import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime, timedelta
# ... 其他import保持不变
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

# 用服务器内存存题目列表，不塞进session
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
    """科目列表缓存，60秒内不重复查询"""
    global _subjects_cache, _subjects_cache_time
    import time
    now = time.time()
    if _subjects_cache is None or (now - _subjects_cache_time) > 60:
        _subjects_cache = list(SUBJECTS.keys())
        _subjects_cache_time = now
    return _subjects_cache

def get_q_by_id(q_id: str):
    """通过ID查找题目"""
    try:
        subject, seq = q_id.split('_', 1)
        for q in ALL_QUESTIONS.get(subject, []):
            if q['seq'] == seq:
                return q
    except Exception:
        pass
    return None

def enrich_question(q: dict) -> dict:
    """为题目附加收藏/笔记/解析/错题信息"""
    q_id = get_question_id(q['subject'], q['seq'])
    q['q_id'] = q_id
    q['is_favorite'] = q_id in db.get_favorite_ids()
    q['note'] = db.get_note(q_id)
    exp = db.get_explanation(q_id)
    q['explanation'] = exp.get('content', '')
    q['exp_source'] = exp.get('source', '')
    conn = db.get_conn()
    wrong = conn.execute(
        'SELECT wrong_count, last_answer FROM wrong_questions WHERE q_id=?', (q_id,)
    ).fetchone()
    conn.close()
    q['wrong_count'] = wrong['wrong_count'] if wrong else 0
    q['last_wrong_answer'] = wrong['last_answer'] if wrong else ''
    return q

# ============================================================
# 主页
# ============================================================
@app.route('/')
def index():
    subjects = _get_subjects_cached()
    stats_all = db.get_stats()
    total_questions = sum(len(v) for v in ALL_QUESTIONS.values())

    today_review = len(db.get_today_review_ids())

    plan = db.get_plan()
    plan_info = None
    if plan:
        today = date.today()
        exam_date = date.fromisoformat(plan['exam_date'])
        days_left = (exam_date - today).days
        today_done = _get_today_answered_count()
        plan_info = {
            'days_left':    max(0, days_left),
            'daily_target': plan['daily_target'],
            'today_done':   today_done,
            'today_remain': max(0, plan['daily_target'] - today_done),
            'total_target': plan['total_target'],
            'total_done':   stats_all['answered'],
            'total_remain': max(0, plan['total_target'] - stats_all['answered']),
        }

    return render_template('index.html',
        subjects=subjects,
        stats=stats_all,
        total_questions=total_questions,
        today_review=today_review,
        plan_info=plan_info,
    )

def _get_today_answered_count():
    conn = db.get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT q_id) as cnt FROM answer_records "
        "WHERE date(answered_at)=date('now','localtime')"
    ).fetchone()
    conn.close()
    return row['cnt']

# ============================================================
# 构建题目列表（练习用）
# ============================================================
def _build_question_list(subject=None, q_type=None, mode='order',
                          range_start=1, range_end=None,
                          filter_mode='all'):
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

    answered_ids = db.get_answered_ids(subject)
    wrong_ids    = {w['q_id'] for w in db.get_wrong_questions(subject)}
    favorite_ids = db.get_favorite_ids(subject)

    if filter_mode == 'undone':
        questions = [q for q in questions
                     if get_question_id(q['subject'], q['seq']) not in answered_ids]
    elif filter_mode == 'done':
        questions = [q for q in questions
                     if get_question_id(q['subject'], q['seq']) in answered_ids]
    elif filter_mode == 'wrong':
        questions = [q for q in questions
                     if get_question_id(q['subject'], q['seq']) in wrong_ids]
    elif filter_mode == 'favorite':
        questions = [q for q in questions
                     if get_question_id(q['subject'], q['seq']) in favorite_ids]

    if mode == 'random':
        random.shuffle(questions)

    return questions

# ============================================================
# 格式化题目（统一处理选项/判断题等）
# ============================================================
def _format_question(q: dict, index: int, total: int) -> dict:
    q = dict(q)
    q_id = get_question_id(q['subject'], q['seq'])
    q['q_id']   = q_id
    q['index']  = index
    q['total']  = total
    q['is_favorite'] = q_id in db.get_favorite_ids()
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
    filter_mode = data.get('filter_mode', 'all')
    range_start = int(data.get('range_start', 1))
    range_end   = int(data.get('range_end')) if data.get('range_end') else None

    questions = _build_question_list(
        subject=subject, q_type=q_type, mode=mode,
        range_start=range_start, range_end=range_end,
        filter_mode=filter_mode
    )

    if not questions:
        return jsonify({'error': '没有符合条件的题目'}), 400

    # ✅ 生成唯一key存到服务器内存，session只存key不存大列表
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
    # ✅ 从服务器内存取，不从session取大列表
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

    db.record_answer(q_id, q['subject'], q['type'], user_answer, is_correct)
    db.update_wrong_book(q_id, q['subject'], user_answer, is_correct)

    display_answer = correct_answer
    if q['type'] == '判断题':
        display_answer = '正确' if correct_answer == 'A' else '错误'

    exp = db.get_explanation(q_id)

    return jsonify({
        'correct':        is_correct,
        'correct_answer': display_answer,
        'user_answer':    user_answer,
        'explanation':    exp.get('content', ''),
        'wrong_count':    _get_wrong_count(q_id),
    })

def _get_wrong_count(q_id):
    conn = db.get_conn()
    row = conn.execute(
        'SELECT wrong_count FROM wrong_questions WHERE q_id=?', (q_id,)
    ).fetchone()
    conn.close()
    return row['wrong_count'] if row else 0

# ============================================================
# 错题本
# ============================================================
@app.route('/wrong_book')
def wrong_book_page():
    subject  = request.args.get('subject', '')
    sort     = request.args.get('sort', 'recent')
    page     = int(request.args.get('page', 1))
    per_page = 10
    subjects = list(SUBJECTS.keys())

    wrong_data = db.get_wrong_questions_page(subject, sort, page, per_page)

    enriched = []
    for w in wrong_data['questions']:
        q = get_q_by_id(w['q_id'])
        if not q:
            continue
        item = dict(q)
        item['q_id']        = w['q_id']
        item['wrong_count'] = w['wrong_count']
        item['last_answer'] = w['last_answer']
        item['next_review'] = w['next_review']

        wc = w['wrong_count']
        if wc >= 4:
            item['level'] = 'danger'
            item['level_text'] = '⚠️ 高危错题'
        elif wc >= 2:
            item['level'] = 'key'
            item['level_text'] = '🔶 重点错题'
        else:
            item['level'] = 'normal'
            item['level_text'] = '📌 普通错题'

        item['correct_answer_display'] = q['answer']
        if q['type'] == '判断题':
            item['correct_answer_display'] = '正确' if q['answer'] == 'A' else '错误'
            la = w['last_answer'] or ''
            item['last_answer_display'] = '正确' if la == 'A' else ('错误' if la == 'B' else la)
        else:
            item['last_answer_display'] = w['last_answer'] or ''

        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})
        item['options'] = options

        exp = db.get_explanation(w['q_id'])
        item['explanation'] = exp.get('content', '')
        enriched.append(item)

    return render_template('wrong_book.html',
        subjects=subjects,
        wrong_questions=enriched,
        total=wrong_data['total'],
        total_pages=wrong_data['total_pages'],
        page=page,
        current_subject=subject,
        sort=sort,
    )

@app.route('/api/wrong_book', methods=['GET'])
def api_wrong_book():
    subject = request.args.get('subject') or None
    level   = request.args.get('level') or None
    wrongs  = db.get_wrong_questions(subject, level)
    result  = []
    for w in wrongs:
        q = get_q_by_id(w['q_id'])
        if not q:
            continue
        item = dict(q)
        item['q_id']        = w['q_id']
        item['wrong_count'] = w['wrong_count']
        item['last_answer'] = w['last_answer']
        item['next_review'] = w['next_review']
        item['mastered']    = w['mastered']
        wc = w['wrong_count']
        if wc >= 4:
            item['level'] = 'danger'
            item['level_text'] = '⚠️ 高危错题'
        elif wc >= 2:
            item['level'] = 'key'
            item['level_text'] = '🔶 重点错题'
        else:
            item['level'] = 'normal'
            item['level_text'] = '📌 普通错题'
        item['correct_answer_display'] = q['answer']
        if q['type'] == '判断题':
            item['correct_answer_display'] = '正确' if q['answer'] == 'A' else '错误'
            item['last_answer_display'] = '正确' if w['last_answer'] == 'A' else '错误'
        else:
            item['last_answer_display'] = w['last_answer']
        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})
        item['options'] = options
        exp = db.get_explanation(w['q_id'])
        item['explanation'] = exp.get('content', '')
        result.append(item)
    return jsonify(result)

@app.route('/api/wrong_book/remove/<q_id>', methods=['POST'])
def api_remove_wrong(q_id):
    db.remove_wrong_question(q_id)
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

    # ✅ 考试题目也存内存，不存session
    exam_key = str(uuid.uuid4())
    exam_ids = [get_question_id(q['subject'], q['seq']) for q in selected]
    _practice_store[exam_key] = exam_ids
    session['exam_key']      = exam_key
    session['exam_duration'] = duration * 60
    session['exam_answers']  = {}
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

    # ✅ 从内存取考试题目列表
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

        db.record_answer(q_id, q['subject'], q['type'], user_answer, is_correct)
        db.update_wrong_book(q_id, q['subject'], user_answer, is_correct)

        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})

        display_correct = correct_answer
        display_user    = user_answer
        if q['type'] == '判断题':
            display_correct = '正确' if correct_answer == 'A' else '错误'
            display_user    = '正确' if user_answer == 'A' else ('错误' if user_answer == 'B' else '未作答')

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
    data    = request.json
    q_id    = data.get('q_id')
    subject = data.get('subject')
    status  = db.toggle_favorite(q_id, subject)
    return jsonify({'favorited': status})

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
    subjects   = list(SUBJECTS.keys())
    stats_list = []
    for sub in subjects:
        s = db.get_stats(sub)
        s['subject']      = sub
        s['total']        = len(ALL_QUESTIONS.get(sub, []))
        s['undone']       = s['total'] - s['answered']
        s['correct_rate'] = round(s['correct'] / s['answered'] * 100, 1) if s['answered'] else 0
        stats_list.append(s)

    full_stats   = db.get_full_stats()
    exam_records = db.get_exam_records(10)

    return render_template('stats.html',
        stats_list=stats_list,
        full_stats=full_stats,
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
    today_tasks     = db.get_today_tasks(subjects)
    week_data       = db.get_week_data()

    return render_template('plan.html',
        plan=plan,
        subjects=subjects,
        total_questions=total_questions,
        today_tasks=today_tasks,
        week_data=week_data,
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
    ids       = db.get_today_review_ids()
    questions = []
    for q_id in ids:
        q = get_q_by_id(q_id)
        if q:
            questions.append(_format_question(q, len(questions), len(ids)))

    # ✅ 复习也用内存存，不塞session
    practice_key = str(uuid.uuid4())
    _practice_store[practice_key] = ids
    session['practice_key']   = practice_key
    session['practice_index'] = 0

    return render_template('review.html', review_questions=questions)

@app.route('/api/today_review')
def api_today_review():
    ids       = db.get_today_review_ids()
    questions = []
    for q_id in ids:
        q = get_q_by_id(q_id)
        if q:
            questions.append(_format_question(q, len(questions), len(ids)))

    # ✅ 复习也用内存存，不塞session
    practice_key = str(uuid.uuid4())
    _practice_store[practice_key] = ids
    session['practice_key']   = practice_key
    session['practice_index'] = 0

    return jsonify({'total': len(questions), 'questions': questions})

# ============================================================
# 启动
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    print("=" * 50)
    print("  📚 电力刷题系统启动中...")
    print("  访问地址：http://localhost:5000")
    print("  手机访问：http://本机IP:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)