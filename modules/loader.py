import os
import pandas as pd
from config import DATA_DIR, SUBJECTS

def load_all_questions():
    """
    读取所有专业Excel题库
    返回：{ '输电': [题目dict, ...], '变电': [...], ... }
    """
    all_questions = {}

    for subject, filename in SUBJECTS.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            print(f"⚠️  找不到文件：{filepath}，已跳过")
            continue

        df = pd.read_excel(filepath, dtype=str)
        df.fillna('', inplace=True)

        questions = []
        for _, row in df.iterrows():
            q = {
                'subject':  subject,
                'seq':      str(row.get('序号', '')).strip(),
                'type':     str(row.get('题型', '')).strip(),
                'stem':     str(row.get('题干', '')).strip(),
                'option_a': str(row.get('选项A', '')).strip(),
                'option_b': str(row.get('选项B', '')).strip(),
                'option_c': str(row.get('选项C', '')).strip(),
                'option_d': str(row.get('选项D', '')).strip(),
                'option_e': str(row.get('选项E', '')).strip(),
                'option_f': str(row.get('选项F', '')).strip(),
                'answer':   str(row.get('答案', '')).strip().upper(),
            }
            # 过滤空行
            if q['stem']:
                questions.append(q)

        all_questions[subject] = questions
        print(f"✅ 已加载 {subject}：{len(questions)} 题")

    return all_questions


def get_question_id(subject: str, seq: str) -> str:
    """生成唯一题目ID"""
    return f"{subject}_{seq}"