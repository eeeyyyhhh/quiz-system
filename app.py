import os
import json
import uuid
import random
import time
from datetime import date, timedelta, datetime

from flask import Flask, render_template, request, jsonify, session, redirect, send_from_directory

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
_subjects_cache      = None
_subjects_cache_time = 0

def _get_subjects_cached():
    global _subjects_cache, _subjects_cache_time
    now = time.time()
    if _subjects_cache is None or (now - _subjects_cache_time) > 60:
        _subjects_cache      = list(SUBJECTS.keys())
        _subjects_cache_time = now
    return _subjects_cache

# ============================================================
# 工具函数
# ============================================================
def get_q_by_id(q_id: str):
    try:
        subject, seq = q_id.split('_', 1)
        for q in ALL_QUESTIONS.get(subject, []):
            if q['seq'] == seq:
                return q
    except Exception:
        pass
    return None


def _build_question_list(subject=None, q_type=None, mode='order',
                         range_start=1, range_end=None):
    questions = []
    subjects  = [subject] if subject else list(SUBJECTS.keys())
    for sub in subjects:
        for q in ALL_QUESTIONS.get(sub, []):
            if q_type and q['type'] != q_type:
                continue
            questions.append(q)

    if range_end:
        questions = [q for q in questions
                     if range_start <= int(q['seq']) <= range_end]

    if mode == 'random':
        random.shuffle(questions)

    return questions


def _format_question(q: dict, index: int, total: int) -> dict:
    q    = dict(q)
    q_id = get_question_id(q['subject'], q['seq'])
    q['q_id']        = q_id
    q['index']       = index
    q['total']       = total
    q['is_favorite'] = False
    q['note']        = db.get_note(q_id)
    exp              = db.get_explanation(q_id)
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
# 主页
# ============================================================
@app.route('/')
def index():
    subjects        = _get_subjects_cached()
    total_questions = sum(len(v) for v in ALL_QUESTIONS.values())
    return render_template('index.html',
        subjects=subjects,
        total_questions=total_questions,
    )

# ============================================================
# 科目题目总数接口
# ============================================================
@app.route('/api/stats/<subject>')
def api_stats_subject(subject):
    total = len(ALL_QUESTIONS.get(subject, []))
    return jsonify({'total': total, 'answered': 0, 'correct_rate': 0})

# ============================================================
# 题目ID列表接口
# ============================================================
@app.route('/api/local/question_ids')
def api_local_question_ids():
    subject = request.args.get('subject') or None
    q_type  = request.args.get('q_type') or None

    result   = []
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
# 全部题目ID接口（给不重复抽题用）
# ============================================================
@app.route('/api/exam/all_ids')
def api_exam_all_ids():
    """返回全库所有题目ID，按题型分组"""
    result = {'单选题': [], '多选题': [], '判断题': []}
    for sub in ALL_QUESTIONS:
        for q in ALL_QUESTIONS[sub]:
            q_id = get_question_id(q['subject'], q['seq'])
            if q['type'] in result:
                result[q['type']].append(q_id)
    return jsonify(result)

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
    ids          = [get_question_id(q['subject'], q['seq']) for q in questions]
    _practice_store[practice_key] = ids
    session['practice_key']   = practice_key
    session['practice_index'] = 0

    return jsonify({
        'total':   len(questions),
        'first_q': _format_question(questions[0], 0, len(questions))
    })


@app.route('/api/practice/start_by_ids', methods=['POST'])
def practice_start_by_ids():
    data  = request.json
    q_ids = data.get('q_ids', [])

    if not q_ids:
        return jsonify({'error': '没有符合条件的题目'}), 400

    questions = [get_q_by_id(qid) for qid in q_ids]
    questions = [q for q in questions if q]

    if not questions:
        return jsonify({'error': '题目数据不存在'}), 400

    practice_key = str(uuid.uuid4())
    ids          = [get_question_id(q['subject'], q['seq']) for q in questions]
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
    ids          = _practice_store.get(practice_key, [])

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
# 错题本
# ============================================================
@app.route('/wrong_book')
def wrong_book_page():
    subjects = list(SUBJECTS.keys())
    return render_template('wrong_book.html', subjects=subjects)


@app.route('/api/wrong_book/questions', methods=['POST'])
def api_wrong_book_questions():
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

        item         = dict(q)
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

        exp                  = db.get_explanation(q_id)
        item['explanation']  = exp.get('content', '')
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
    duration = int(data.get('duration', 60))
    ratio    = data.get('ratio', {
        '单选题': 40,
        '多选题': 40,
        '判断题': 40,
    })
    # 前端传入要排除的题目ID（不重复模式）
    exclude_ids = set(data.get('exclude_ids', []))

    all_qs = _build_question_list(subject=subject, mode='random')
    if not all_qs:
        return jsonify({'error': '题库为空'}), 400

    # 过滤已做过的题目
    if exclude_ids:
        filtered = [q for q in all_qs
                    if get_question_id(q['subject'], q['seq']) not in exclude_ids]
        # 检查剩余题目是否足够
        type_count = {}
        for q in filtered:
            type_count[q['type']] = type_count.get(q['type'], 0) + 1
        total_needed = sum(ratio.values())
        total_remain = sum(type_count.values())

        if total_remain < total_needed:
            return jsonify({
                'error': 'not_enough',
                'remain': total_remain,
                'needed': total_needed,
            }), 400
        all_qs = filtered

    type_map = {}
    for q in all_qs:
        type_map.setdefault(q['type'], []).append(q)

    selected = []
    shortage = []

    for q_type, count in ratio.items():
        pool = type_map.get(q_type, [])
        random.shuffle(pool)
        got = pool[:count]
        selected += got
        if len(got) < count:
            shortage.append(f'{q_type}仅有{len(got)}题（需要{count}题）')

    if not selected:
        return jsonify({'error': '题库中无可用题目'}), 400

    type_order = {'单选题': 0, '多选题': 1, '判断题': 2}
    selected.sort(key=lambda q: type_order.get(q['type'], 9))

    total_count = len(selected)

    exam_key = str(uuid.uuid4())
    exam_ids = [get_question_id(q['subject'], q['seq']) for q in selected]
    _practice_store[exam_key]    = exam_ids
    session['exam_key']          = exam_key
    session['exam_duration']     = duration * 60
    session['exam_subject']      = subject or '综合'

    formatted = [_format_question(q, i, total_count)
                 for i, q in enumerate(selected)]
    for q in formatted:
        q.pop('answer', None)

    resp = {
        'total':     total_count,
        'duration':  duration * 60,
        'questions': formatted,
        'exam_ids':  exam_ids,   # 返回本次题目ID，前端存入已做列表
    }
    if shortage:
        resp['warning'] = '；'.join(shortage)

    return jsonify(resp)


@app.route('/api/exam/submit', methods=['POST'])
def exam_submit():
    data     = request.json
    answers  = data.get('answers', {})
    duration = int(data.get('duration', 0))

    exam_key = session.get('exam_key', '')
    ids      = _practice_store.get(exam_key, [])
    if not ids:
        return jsonify({'error': '考试会话已过期，请重新开始考试'}), 400

    total        = len(ids)
    score        = 0.0
    correct_count = 0
    details      = []

    # 分值配置
    score_map = {'单选题': 1.0, '多选题': 1.0, '判断题': 0.5}

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
            correct_count += 1
            score += score_map.get(q['type'], 1.0)

        options = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            val = q.get(f'option_{key.lower()}', '')
            if val:
                options.append({'key': key, 'text': val})

        display_correct = correct_answer
        display_user    = user_answer
        if q['type'] == '判断题':
            display_correct = '正确' if correct_answer == 'A' else '错误'
            display_user    = (
                '正确'  if user_answer == 'A' else
                '错误'  if user_answer == 'B' else
                '未作答'
            )
            options = [
                {'key': 'A', 'text': '正确'},
                {'key': 'B', 'text': '错误'},
            ]

        exp = db.get_explanation(q_id)
        details.append({
            'q_id':           q_id,
            'subject':        q['subject'],
            'stem':           q['stem'],
            'type':           q['type'],
            'options':        options,
            'correct_answer': display_correct,
            'user_answer':    display_user,
            'is_correct':     is_correct,
            'score':          score_map.get(q['type'], 1.0),
            'explanation':    exp.get('content', ''),
        })

    score         = round(score, 1)
    subject_label = session.get('exam_subject', '综合')

    db.save_exam_record(
        subject_label, total, correct_count, score, duration,
        json.dumps(details, ensure_ascii=False)
    )

    # 返回本次考试ID，供前端存入历史记录
    exam_record_id = db.get_last_exam_id()

    return jsonify({
        'total':         total,
        'correct':       correct_count,
        'score':         score,
        'duration':      duration,
        'details':       details,
        'exam_record_id': exam_record_id,
    })


# ============================================================
# 考试记录页面
# ============================================================
@app.route('/exam_records')
def exam_records_page():
    return render_template('exam_records.html')


@app.route('/api/exam/records')
def api_exam_records():
    """获取最近15次考试记录"""
    records = db.get_exam_records(15)
    result  = []
    for r in records:
        item = {
            'id':         r['id'],
            'subject':    r['subject'],
            'total':      r['total'],
            'correct':    r['correct'],
            'score':      r['score'],
            'duration':   r['duration'],
            'created_at': r['created_at'],
        }
        result.append(item)
    return jsonify(result)


@app.route('/api/exam/record/<int:record_id>')
def api_exam_record_detail(record_id):
    """获取单次考试详情（含错题，用于重做）"""
    record = db.get_exam_record_by_id(record_id)
    if not record:
        return jsonify({'error': '记录不存在'}), 404
    detail = json.loads(record['detail']) if record['detail'] else []
    return jsonify({
        'id':         record['id'],
        'subject':    record['subject'],
        'total':      record['total'],
        'correct':    record['correct'],
        'score':      record['score'],
        'duration':   record['duration'],
        'created_at': record['created_at'],
        'details':    detail,
    })


@app.route('/api/exam/record/<int:record_id>/retry', methods=['POST'])
def api_exam_record_retry(record_id):
    """重做某次考试的错题"""
    record = db.get_exam_record_by_id(record_id)
    if not record:
        return jsonify({'error': '记录不存在'}), 404

    details    = json.loads(record['detail']) if record['detail'] else []
    wrong_ids  = [d['q_id'] for d in details if not d['is_correct']]

    if not wrong_ids:
        return jsonify({'error': '本次考试没有错题'}), 400

    questions = [get_q_by_id(qid) for qid in wrong_ids]
    questions = [q for q in questions if q]

    if not questions:
        return jsonify({'error': '题目数据不存在'}), 400

    total_count  = len(questions)
    practice_key = str(uuid.uuid4())
    ids          = [get_question_id(q['subject'], q['seq']) for q in questions]
    _practice_store[practice_key]  = ids
    session['exam_key']            = practice_key
    session['exam_duration']       = 3600
    session['exam_subject']        = record['subject'] or '综合'

    formatted = [_format_question(q, i, total_count)
                 for i, q in enumerate(questions)]
    for q in formatted:
        q.pop('answer', None)

    return jsonify({
        'total':     total_count,
        'duration':  3600,
        'questions': formatted,
        'exam_ids':  ids,
        'is_retry':  True,
    })

# ============================================================
# 收藏
# ============================================================
@app.route('/api/favorite', methods=['POST'])
def api_favorite():
    return jsonify({'favorited': False})

# ============================================================
# 笔记
# ============================================================
@app.route('/api/note', methods=['POST'])
def api_note():
    data    = request.json
    q_id    = data.get('q_id')
    content = data.get('content', '')
    db.save_note(q_id, content)
    return jsonify({'ok': True})

# ============================================================
# 解析
# ============================================================
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
    subjects        = list(SUBJECTS.keys())
    subject_totals  = {sub: len(ALL_QUESTIONS.get(sub, [])) for sub in subjects}
    total_questions = sum(subject_totals.values())
    exam_records    = db.get_exam_records(10)
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
    return jsonify({'total': 0, 'questions': []})

# ============================================================
# PWA - Service Worker
# ============================================================
@app.route('/sw.js')
def service_worker():
    return send_from_directory('static/js', 'sw.js',
                               mimetype='application/javascript')

# ============================================================
# 启动
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("  📚 电力刷题系统启动中...")
    print(f"  访问地址：http://localhost:{port}")
    print("  手机访问：http://本机IP:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)