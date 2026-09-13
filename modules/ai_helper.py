from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

def generate_explanation(question: dict) -> str:
    """
    调用DeepSeek为题目生成解析
    question: 包含stem, options, answer, subject, type的字典
    """
    # 构建选项文本
    options_text = ''
    for key in ['A', 'B', 'C', 'D', 'E', 'F']:
        val = question.get(f'option_{key.lower()}', '')
        if val:
            options_text += f'\n{key}. {val}'

    # 处理判断题答案显示
    answer = question.get('answer', '')
    if question.get('type') == '判断题':
        answer_display = '正确' if answer == 'A' else '错误'
    else:
        answer_display = answer

    prompt = f"""你是一名电力行业专业考试辅导老师，请为以下题目提供简明扼要的解析。

专业领域：{question.get('subject', '')}
题目类型：{question.get('type', '')}
题干：{question.get('stem', '')}
{options_text}
正确答案：{answer_display}

请从以下角度解析（200字以内）：
1. 为什么选这个答案
2. 关键知识点说明
3. 易错点提示（如有）

直接输出解析内容，不要加"解析："前缀。"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f'AI解析生成失败：{str(e)}'