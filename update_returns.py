#!/usr/bin/env python3
"""批量更新 app_v2.py 中的返回值，添加进度条"""
import re

# 读取文件
with open('/Users/hecf23/work/money-print/app_v2.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 需要添加 progress_html 的return语句的模式
# 匹配形如 return "xxxx", gr.update(...), "", None, None 的语句

def add_progress_bar(match):
    """在return语句前添加progress_html"""
    indent = match.group(1)
    rest = match.group(2)

    # 如果已经包含progress_html，则跳过
    if 'progress_html' in rest or 'generate_progress_bar' in rest:
        return match.group(0)

    # 添加progress_html作为第一个返回值
    return f'{indent}return progress_html, {rest}'

# 处理所有步骤函数中的return语句
# 先找到每个步骤函数的范围
lines = content.split('\n')
new_lines = []
in_step_function = False
function_name = ""

for i, line in enumerate(lines):
    # 检测函数开始
    if re.match(r'^(async )?def (step_\d+_\w+|view_session_status|create_new_session)\(', line):
        in_step_function = True
        function_name = line
        new_lines.append(line)
        continue

    # 检测函数结束（下一个函数或类的定义）
    if in_step_function and re.match(r'^(async )?def |^class ', line):
        in_step_function = False

    # 在步骤函数内部处理return语句
    if in_step_function and 'return' in line:
        # 检查是否已经有progress相关
        if 'progress_html' not in line and 'generate_progress_bar' not in line:
            # 如果return后面跟着的不是进度条，则需要添加
            # 检查是否返回多个值
            match = re.match(r'(\s+)return\s+(.+)', line)
            if match:
                indent = match.group(1)
                rest = match.group(2)

                # 检查返回值个数 - 我们需要5个返回值的情况（除了create_new_session是6个）
                # 如果返回值少于5个，说明已经是旧格式，需要添加progress
                # 简单判断：如果不包含 progress_html 或 generate_progress_bar，在前面添加

                # 对于错误返回（通常较短），直接在前面添加 generate_progress_bar([])
                if '❌' in rest and 'visible=False' in rest:
                    # 获取前导状态（需要添加进度条）
                    # 先检查前面是否已经获取了 progress_html
                    prev_lines_text = '\n'.join(lines[max(0, i-10):i])
                    if 'progress_html = generate_progress_bar' not in prev_lines_text:
                        new_lines.append(f'{indent}return generate_progress_bar([]), {rest}')
                        continue

                # 对于成功返回，应该使用从status获取的progress_html
                elif '✅' in rest:
                    # 检查前面是否已经有progress_html定义
                    prev_lines_text = '\n'.join(lines[max(0, i-20):i])
                    if 'progress_html = generate_progress_bar' in prev_lines_text:
                        # 已经定义了，直接添加到返回值前面
                        new_lines.append(f'{indent}return progress_html, {rest}')
                        continue
                    elif 'status = workflow.get_session_status' in prev_lines_text:
                        # 需要在return前添加progress_html生成
                        # 先添加progress_html定义
                        new_lines.insert(len(new_lines), f"{indent}progress_html = generate_progress_bar(status['completed_steps'])")
                        new_lines.append(f'{indent}return progress_html, {rest}')
                        continue

    new_lines.append(line)

# 写回文件
content = '\n'.join(new_lines)

with open('/Users/hecf23/work/money-print/app_v2_updated.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 更新完成！文件保存为 app_v2_updated.py")
print("请检查后手动替换 app_v2.py")
