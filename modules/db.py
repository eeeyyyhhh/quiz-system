import sqlite3
import os
import json
from datetime import datetime, timedelta, date
from config import DB_PATH

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化所有数据表"""
    conn = get_conn()
    c = conn.cursor()

    # 答题记录表
    c.execute('''
        CREATE TABLE IF NOT EXISTS answer_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            q_id        TEXT NOT NULL,
            subject     TEXT NOT NULL,
            q_type      TEXT NOT NULL,
            user_answer TEXT NOT NULL,
            correct     INTEGER NOT NULL,
            answered_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # ✅ 答题记录索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_ar_qid ON answer_records(q_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ar_subject ON answer_records(subject)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ar_date ON answer_records(answered_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ar_correct ON answer_records(correct)')

    # 错题本表
    c.execute('''
        CREATE TABLE IF NOT EXISTS wrong_questions (
            q_id          TEXT PRIMARY KEY,
            subject       TEXT NOT NULL,
            wrong_count   INTEGER DEFAULT 1,
            last_answer   TEXT,
            next_review   DATE,
            correct_streak INTEGER DEFAULT 0,
            mastered      INTEGER DEFAULT 0,
            updated_at    DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # ✅ 错题本索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_wq_subject ON wrong_questions(subject)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_wq_mastered ON wrong_questions(mastered)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_wq_review ON wrong_questions(next_review)')

    # 收藏表
    c.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            q_id       TEXT PRIMARY KEY,
            subject    TEXT NOT NULL,
            created_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # ✅ 收藏索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_fav_subject ON favorites(subject)')

    # 笔记表
    c.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            q_id       TEXT PRIMARY KEY,
            content    TEXT DEFAULT '',
            updated_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # 解析表
    c.execute('''
        CREATE TABLE IF NOT EXISTS explanations (
            q_id       TEXT PRIMARY KEY,
            content    TEXT DEFAULT '',
            source     TEXT DEFAULT 'manual',
            updated_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # 考试记录表
    c.execute('''
        CREATE TABLE IF NOT EXISTS exam_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT,
            total       INTEGER,
            correct     INTEGER,
            score       REAL,
            duration    INTEGER,
            detail      TEXT,
            created_at  DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    # 学习计划表
    c.execute('''
        CREATE TABLE IF NOT EXISTS study_plan (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_date    DATE NOT NULL,
            total_target INTEGER NOT NULL,
            daily_target INTEGER NOT NULL,
            focus_subject TEXT DEFAULT '',
            created_at   DATETIME DEFAULT (datetime('now','localtime'))
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")


# ============================================================
# 答题记录相关
# ============================================================

def record_answer(q_id, subject, q_type, user_answer, correct: bool):
    """记录一次答题"""
    conn = get_conn()
    conn.execute(
        'INSERT INTO answer_records (q_id, subject, q_type, user_answer, correct) VALUES (?,?,?,?,?)',
        (q_id, subject, q_type, user_answer, 1 if correct else 0)
    )
    conn.commit()
    conn.close()


def get_answered_ids(subject=None):
    """获取已做过的题目ID集合"""
    conn = get_conn()
    if subject:
        rows = conn.execute(
            'SELECT DISTINCT q_id FROM answer_records WHERE subject=?', (subject,)
        ).fetchall()
    else:
        rows = conn.execute('SELECT DISTINCT q_id FROM answer_records').fetchall()
    conn.close()
    return {r['q_id'] for r in rows}


def get_correct_ids(subject=None):
    """获取答对过的题目ID集合（最近一次答对）"""
    conn = get_conn()
    if subject:
        rows = conn.execute('''
            SELECT q_id, correct FROM answer_records
            WHERE subject=? AND id IN (
                SELECT MAX(id) FROM answer_records WHERE subject=? GROUP BY q_id
            )
        ''', (subject, subject)).fetchall()
    else:
        rows = conn.execute('''
            SELECT q_id, correct FROM answer_records
            WHERE id IN (SELECT MAX(id) FROM answer_records GROUP BY q_id)
        ''').fetchall()
    conn.close()
    return {r['q_id'] for r in rows if r['correct'] == 1}


# ============================================================
# 错题本相关
# ============================================================

def update_wrong_book(q_id, subject, user_answer, correct: bool):
    """更新错题本"""
    from config import REVIEW_INTERVALS, MASTERED_CORRECT_STREAK

    conn = get_conn()
    row = conn.execute('SELECT * FROM wrong_questions WHERE q_id=?', (q_id,)).fetchone()
    today = date.today()

    if not correct:
        if row is None:
            next_review = today
            conn.execute(
                '''INSERT INTO wrong_questions
                   (q_id, subject, wrong_count, last_answer, next_review, correct_streak, mastered)
                   VALUES (?,?,1,?,?,0,0)''',
                (q_id, subject, user_answer, next_review.isoformat())
            )
        else:
            wc = row['wrong_count'] + 1
            interval = REVIEW_INTERVALS.get(wc, 7)
            next_review = today + timedelta(days=interval)
            conn.execute(
                '''UPDATE wrong_questions
                   SET wrong_count=?, last_answer=?, next_review=?,
                       correct_streak=0, mastered=0, updated_at=datetime('now','localtime')
                   WHERE q_id=?''',
                (wc, user_answer, next_review.isoformat(), q_id)
            )
    else:
        if row is not None:
            streak = row['correct_streak'] + 1
            mastered = 1 if streak >= MASTERED_CORRECT_STREAK else 0
            conn.execute(
                '''UPDATE wrong_questions
                   SET correct_streak=?, mastered=?, updated_at=datetime('now','localtime')
                   WHERE q_id=?''',
                (streak, mastered, q_id)
            )

    conn.commit()
    conn.close()


def get_wrong_questions(subject=None, level=None):
    """获取错题列表"""
    from config import WRONG_LEVEL
    conn = get_conn()
    sql = 'SELECT * FROM wrong_questions WHERE mastered=0'
    params = []
    if subject:
        sql += ' AND subject=?'
        params.append(subject)
    if level and level in WRONG_LEVEL:
        lo, hi = WRONG_LEVEL[level]
        sql += ' AND wrong_count>=? AND wrong_count<=?'
        params += [lo, hi]
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_wrong_questions_page(subject='', sort='recent', page=1, per_page=10):
    """
    获取错题列表（分页版，给错题本页面用）
    返回: {'questions': [...], 'total': n, 'total_pages': n}
    """
    conn = get_conn()

    where = 'WHERE mastered=0'
    params = []
    if subject:
        where += ' AND subject=?'
        params.append(subject)

    order = 'wrong_count DESC' if sort == 'most' else 'updated_at DESC'

    count_row = conn.execute(
        f'SELECT COUNT(*) as cnt FROM wrong_questions {where}', params
    ).fetchone()
    total = count_row['cnt']
    total_pages = max(1, (total + per_page - 1) // per_page)

    offset = (page - 1) * per_page
    rows = conn.execute(
        f'SELECT * FROM wrong_questions {where} ORDER BY {order} LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()
    conn.close()

    return {
        'questions': [dict(r) for r in rows],
        'total': total,
        'total_pages': total_pages
    }


def remove_wrong_question(q_id):
    """从错题本移除（标记已掌握）"""
    conn = get_conn()
    conn.execute(
        "UPDATE wrong_questions SET mastered=1, updated_at=datetime('now','localtime') WHERE q_id=?",
        (q_id,)
    )
    conn.commit()
    conn.close()


def get_today_review_ids():
    """获取今天需要复习的错题ID"""
    today = date.today().isoformat()
    conn = get_conn()
    rows = conn.execute(
        'SELECT q_id FROM wrong_questions WHERE next_review<=? AND mastered=0',
        (today,)
    ).fetchall()
    conn.close()
    return [r['q_id'] for r in rows]


# ============================================================
# 收藏相关
# ============================================================

def toggle_favorite(q_id, subject):
    """收藏/取消收藏，返回当前状态"""
    conn = get_conn()
    row = conn.execute('SELECT q_id FROM favorites WHERE q_id=?', (q_id,)).fetchone()
    if row:
        conn.execute('DELETE FROM favorites WHERE q_id=?', (q_id,))
        status = False
    else:
        conn.execute('INSERT INTO favorites (q_id, subject) VALUES (?,?)', (q_id, subject))
        status = True
    conn.commit()
    conn.close()
    return status


def get_favorite_ids(subject=None):
    conn = get_conn()
    if subject:
        rows = conn.execute('SELECT q_id FROM favorites WHERE subject=?', (subject,)).fetchall()
    else:
        rows = conn.execute('SELECT q_id FROM favorites').fetchall()
    conn.close()
    return {r['q_id'] for r in rows}


# ============================================================
# 笔记相关
# ============================================================

def save_note(q_id, content):
    conn = get_conn()
    conn.execute(
        '''INSERT INTO notes (q_id, content) VALUES (?,?)
           ON CONFLICT(q_id) DO UPDATE SET content=?, updated_at=datetime('now','localtime')''',
        (q_id, content, content)
    )
    conn.commit()
    conn.close()


def get_note(q_id):
    conn = get_conn()
    row = conn.execute('SELECT content FROM notes WHERE q_id=?', (q_id,)).fetchone()
    conn.close()
    return row['content'] if row else ''


# ============================================================
# 解析相关
# ============================================================

def save_explanation(q_id, content, source='manual'):
    conn = get_conn()
    conn.execute(
        '''INSERT INTO explanations (q_id, content, source) VALUES (?,?,?)
           ON CONFLICT(q_id) DO UPDATE SET content=?, source=?, updated_at=datetime('now','localtime')''',
        (q_id, content, source, content, source)
    )
    conn.commit()
    conn.close()


def get_explanation(q_id):
    conn = get_conn()
    row = conn.execute('SELECT content, source FROM explanations WHERE q_id=?', (q_id,)).fetchone()
    conn.close()
    return dict(row) if row else {'content': '', 'source': ''}


# ============================================================
# 统计相关
# ============================================================

def get_stats(subject=None):
    """获取统计数据（首页用）"""
    conn = get_conn()
    stats = {}

    base_where = 'WHERE subject=?' if subject else ''
    params = (subject,) if subject else ()

    row = conn.execute(
        f'SELECT COUNT(DISTINCT q_id) as cnt FROM answer_records {base_where}', params
    ).fetchone()
    stats['answered'] = row['cnt']

    if subject:
        row = conn.execute('''
            SELECT COUNT(*) as cnt FROM (
                SELECT q_id, correct FROM answer_records
                WHERE subject=? AND id IN (
                    SELECT MAX(id) FROM answer_records WHERE subject=? GROUP BY q_id
                )
            ) WHERE correct=1
        ''', (subject, subject)).fetchone()
    else:
        row = conn.execute('''
            SELECT COUNT(*) as cnt FROM (
                SELECT q_id, correct FROM answer_records
                WHERE id IN (SELECT MAX(id) FROM answer_records GROUP BY q_id)
            ) WHERE correct=1
        ''').fetchone()
    stats['correct'] = row['cnt']

    row = conn.execute(
        f'SELECT COUNT(*) as cnt FROM wrong_questions WHERE mastered=0 {"AND subject=?" if subject else ""}',
        params
    ).fetchone()
    stats['wrong'] = row['cnt']

    row = conn.execute(
        f'SELECT COUNT(*) as cnt FROM favorites {base_where}', params
    ).fetchone()
    stats['favorites'] = row['cnt']

    conn.close()
    return stats


def get_full_stats():
    """获取完整统计数据（统计页面用）"""
    conn = get_conn()
    result = {}

    row = conn.execute('SELECT COUNT(*) as cnt FROM answer_records').fetchone()
    result['total_answered'] = row['cnt']

    row = conn.execute(
        'SELECT ROUND(SUM(correct)*100.0/COUNT(*), 1) as rate FROM answer_records'
    ).fetchone()
    result['correct_rate'] = row['rate'] or 0

    row = conn.execute('SELECT COUNT(*) as cnt FROM wrong_questions WHERE mastered=0').fetchone()
    result['wrong_count'] = row['cnt']

    row = conn.execute(
        "SELECT COUNT(DISTINCT DATE(answered_at)) as cnt FROM answer_records"
    ).fetchone()
    result['study_days'] = row['cnt']

    # 连续打卡
    rows = conn.execute(
        "SELECT DISTINCT DATE(answered_at) as d FROM answer_records ORDER BY d DESC"
    ).fetchall()
    dates = [r['d'] for r in rows]
    streak = 0
    today = date.today()
    for i, d in enumerate(dates):
        check = today - timedelta(days=i)
        if str(check) == d:
            streak += 1
        else:
            break
    result['streak_days'] = streak

    # 各科目统计
    rows = conn.execute('''
        SELECT subject,
               COUNT(*) as answered,
               ROUND(SUM(correct)*100.0/COUNT(*), 1) as rate
        FROM answer_records
        GROUP BY subject
    ''').fetchall()
    result['subject_stats'] = {
        r['subject']: {'answered': r['answered'], 'rate': r['rate'] or 0}
        for r in rows
    }

    # 最近7天
    daily = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM answer_records WHERE DATE(answered_at)=?", (d,)
        ).fetchone()
        daily.append({'date': d[5:], 'count': row['cnt']})
    result['daily_stats'] = daily

    # 题型分布
    rows = conn.execute('''
        SELECT q_type,
               SUM(correct) as correct,
               SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) as wrong,
               ROUND(SUM(correct)*100.0/COUNT(*), 1) as rate
        FROM answer_records
        GROUP BY q_type
    ''').fetchall()
    result['type_stats'] = {
        r['q_type']: {
            'correct': r['correct'],
            'wrong': r['wrong'],
            'rate': r['rate'] or 0
        }
        for r in rows
    }

    conn.close()
    return result


# ============================================================
# 考试记录
# ============================================================

def save_exam_record(subject, total, correct, score, duration, detail_json):
    conn = get_conn()
    conn.execute(
        'INSERT INTO exam_records (subject, total, correct, score, duration, detail) VALUES (?,?,?,?,?,?)',
        (subject, total, correct, score, duration, detail_json)
    )
    conn.commit()
    conn.close()


def get_exam_records(limit=20):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM exam_records ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 学习计划
# ============================================================

def save_plan(exam_date, total_target, daily_target, focus_subject=''):
    conn = get_conn()
    conn.execute('DELETE FROM study_plan')
    conn.execute(
        'INSERT INTO study_plan (exam_date, total_target, daily_target, focus_subject) VALUES (?,?,?,?)',
        (exam_date, total_target, daily_target, focus_subject)
    )
    conn.commit()
    conn.close()


def get_plan():
    conn = get_conn()
    row = conn.execute('SELECT * FROM study_plan ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    if not row:
        return None
    plan = dict(row)
    if plan.get('exam_date'):
        try:
            exam = datetime.strptime(plan['exam_date'], '%Y-%m-%d').date()
            plan['days_left'] = max(0, (exam - date.today()).days)
        except Exception:
            plan['days_left'] = 0
    return plan


def get_today_tasks(subjects_list):
    """获取今日各科目任务完成情况"""
    plan = get_plan()
    if not plan or not subjects_list:
        return []

    daily_target = plan.get('daily_target', 50)
    target_per = max(5, daily_target // len(subjects_list))
    today = date.today().isoformat()

    conn = get_conn()
    tasks = []
    for subject in subjects_list:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM answer_records WHERE subject=? AND DATE(answered_at)=?",
            (subject, today)
        ).fetchone()
        done = row['cnt']
        tasks.append({
            'subject': subject,
            'target': target_per,
            'done': done,
            'progress': min(100, round(done / target_per * 100)) if target_per > 0 else 0
        })
    conn.close()
    return tasks


def get_week_data():
    """获取本周每天答题情况"""
    plan = get_plan()
    daily_target = plan['daily_target'] if plan else 50

    today = date.today()
    weekday = today.weekday()
    week_start = today - timedelta(days=weekday)

    conn = get_conn()
    week_data = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM answer_records WHERE DATE(answered_at)=?",
            (str(d),)
        ).fetchone()
        week_data.append({
            'date': str(d),
            'done': row['cnt'],
            'target': daily_target,
            'is_today': (d == today)
        })
    conn.close()
    return week_data


# ============================================================
# 今日复习
# ============================================================

def get_review_questions(question_loader_func):
    """
    获取今日需要复习的题目
    question_loader_func: 传入一个函数，接收 q_id 返回题目dict
    """
    review_ids = get_today_review_ids()
    questions = []
    for q_id in review_ids:
        q = question_loader_func(q_id)
        if q:
            questions.append(q)
    return questions