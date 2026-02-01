"""AI视频创作智能体 V2 - 符合PRD的6步流程，支持会话恢复

流程（符合PRD）：
1. 提交脚本和参数
2. 优化脚本
3. 生成素材图
4. 生成分片脚本
5. 生成首尾帧
6. 生成视频
"""
import gradio as gr
import logging
from pathlib import Path
from datetime import datetime
from collections import deque

from src.config import (
    RESOLUTION_OPTIONS,
    ASPECT_RATIO_OPTIONS,
    LANGUAGE_OPTIONS,
    STYLE_OPTIONS,
    PERSPECTIVE_OPTIONS,
)
from src.agents.workflow_v2 import VideoCreationWorkflowV2

# 镜头运动选项
CAMERA_MOVEMENT_OPTIONS = [
    "static",   # 静止
    "pan",      # 水平摇镜
    "tilt",     # 垂直摇镜
    "zoom",     # 变焦
    "track",    # 推轨
    "crane",    # 升降
]

# 日志缓冲区 - 用于在前端显示
log_buffer = deque(maxlen=100)  # 最多保留100条日志

class LogHandler(logging.Handler):
    """自定义日志处理器，将日志写入缓冲区"""
    def emit(self, record):
        try:
            msg = self.format(record)
            log_buffer.append(msg)
        except Exception:
            self.handleError(record)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_v2_improved.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 添加自定义日志处理器
log_handler = LogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(log_handler)

logger = logging.getLogger(__name__)

logger.info("正在初始化工作流...")
workflow = VideoCreationWorkflowV2()
logger.info("工作流初始化完成")

# 当前会话ID
current_session_id = None

# 定义步骤信息（6步，符合PRD）
STEPS = [
    {"id": 1, "name": "submit_script_and_params", "title": "提交脚本和参数", "icon": "📝"},
    {"id": 2, "name": "optimize_script", "title": "优化脚本", "icon": "✨"},
    {"id": 3, "name": "generate_material_images", "title": "生成素材图", "icon": "🖼️"},
    {"id": 4, "name": "generate_segment_scripts", "title": "生成分片脚本", "icon": "📋"},
    {"id": 5, "name": "generate_segment_frames", "title": "生成首尾帧", "icon": "🎬"},
    {"id": 6, "name": "generate_videos", "title": "生成视频", "icon": "🎥"},
]


def generate_step_button_css() -> str:
    """生成步骤按钮的CSS样式"""
    return """
    <style>
    /* 步骤按钮容器样式 */
    .step-buttons-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 15px 10px;
        margin: 10px 0;
    }
    .step-buttons-row {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        position: relative;
    }
    /* 步骤之间的连接线 */
    .step-buttons-row::before {
        content: '';
        position: absolute;
        top: 25px;
        left: 40px;
        right: 40px;
        height: 3px;
        background: rgba(255, 255, 255, 0.3);
        z-index: 0;
    }
    </style>
    """


def get_step_button_style(step_id: int, completed_steps: list[str], selected_step: int = None) -> str:
    """根据步骤状态返回按钮的variant"""
    step = STEPS[step_id - 1]
    is_completed = step["name"] in completed_steps
    is_current = not is_completed and (step_id == 1 or STEPS[step_id - 2]["name"] in completed_steps)
    is_selected = selected_step == step_id

    if is_selected:
        return "primary"
    elif is_completed:
        return "secondary"
    elif is_current:
        return "primary"
    else:
        return "secondary"


def get_step_button_label(step_id: int, completed_steps: list[str]) -> str:
    """根据步骤状态返回按钮的标签"""
    step = STEPS[step_id - 1]
    is_completed = step["name"] in completed_steps
    icon = "✓" if is_completed else step["icon"]
    return f"{icon} {step['title']}"


def get_logs() -> str:
    """获取当前日志内容"""
    return "\n".join(log_buffer)


def clear_logs():
    """清空日志缓冲区"""
    log_buffer.clear()


def get_next_step_info(completed_steps: list[str]) -> dict:
    """获取下一步信息"""
    for step in STEPS:
        if step["name"] not in completed_steps:
            return step
    return None


def format_session_info(session_id: str, status: dict) -> str:
    """格式化会话信息显示"""
    created = status.get('created_at', '')
    updated = status.get('updated_at', '')

    # 解析时间
    try:
        created_time = datetime.fromisoformat(created).strftime('%Y-%m-%d %H:%M:%S')
        updated_time = datetime.fromisoformat(updated).strftime('%Y-%m-%d %H:%M:%S')
    except:
        created_time = created
        updated_time = updated

    return f"""**会话ID**: `{session_id[:8]}...`
**创建时间**: {created_time}
**更新时间**: {updated_time}
**进度**: {status.get('progress', 'N/A')}"""


def load_session_data(session_id: str) -> tuple:
    """加载会话数据（脚本和参数）"""
    status = workflow.get_session_status(session_id)
    step_results = status.get('step_results', {})

    # 尝试从步骤1获取数据
    submit_data = step_results.get('submit_script_and_params', {})
    if submit_data:
        script = submit_data.get('original_script', '')
        params = submit_data.get('video_params', {})
        return (
            script,
            params.get('resolution', '1080p'),
            params.get('aspect_ratio', '16:9'),
            params.get('language', 'zh-CN'),
            params.get('style', 'cinematic'),
            params.get('perspective', 'third_person')
        )

    # 默认值
    return ('', '1080p', '16:9', 'zh-CN', 'cinematic', 'third_person')


def get_step_component_visibility(step_id: int) -> dict:
    """根据步骤ID返回各组件的可见性

    | 步骤 | script_output | images_gallery | videos_output | fetch_btn |
    |------|---------------|----------------|---------------|-----------|
    | 1    | 隐藏          | 隐藏           | 隐藏          | 隐藏      |
    | 2    | **显示**      | 隐藏           | 隐藏          | 隐藏      |
    | 3    | 隐藏          | **显示**       | 隐藏          | **显示**  |
    | 4    | 隐藏          | 隐藏           | 隐藏          | 隐藏      |
    | 5    | 隐藏          | **显示**       | 隐藏          | 隐藏      |
    | 6    | 隐藏          | 隐藏           | **显示**      | 隐藏      |
    """
    visibility = {
        "script_visible": False,
        "images_visible": False,
        "videos_visible": False,
    }

    if step_id == 2:
        visibility["script_visible"] = True
    elif step_id == 3:
        visibility["images_visible"] = True
    elif step_id == 5:
        visibility["images_visible"] = True
    elif step_id == 6:
        visibility["videos_visible"] = True

    return visibility


def load_single_step_output(session_id: str, step_id: int) -> tuple:
    """加载单个步骤的输出内容

    返回: (output_text, script_output, images_output, videos_output)
    """
    if not session_id:
        return ("请先创建会话", "", None, None)

    status = workflow.get_session_status(session_id)
    step_results = status.get('step_results', {})
    completed_steps = status.get('completed_steps', [])

    step_info = STEPS[step_id - 1] if 1 <= step_id <= len(STEPS) else None
    if not step_info:
        return ("无效的步骤", "", None, None)

    step_name = step_info["name"]
    step_title = step_info["title"]

    output_text = ""
    script_output = ""
    images_output = []
    videos_output = []

    # 检查步骤是否已完成
    if step_name not in completed_steps:
        # 检查是否是当前步骤
        next_step = get_next_step_info(completed_steps)
        if next_step and next_step["id"] == step_id:
            return (f"## {step_info['icon']} {step_title}\n\n**状态**: 等待执行\n\n点击【下一步】按钮开始执行此步骤", "", None, None)
        else:
            return (f"## {step_info['icon']} {step_title}\n\n**状态**: 未到达\n\n请先完成前面的步骤", "", None, None)

    # 根据步骤ID加载对应的输出
    if step_id == 1:
        # 步骤1：提交脚本和参数
        submit_data = step_results.get('submit_script_and_params', {})
        if submit_data:
            params = submit_data.get('video_params', {})
            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**原始脚本长度**: {submit_data.get('script_length', 0)} 字符

**视频参数**:
- 分辨率: {params.get('resolution', 'N/A')}
- 宽高比: {params.get('aspect_ratio', 'N/A')}
- 语言: {params.get('language', 'N/A')}
- 美学风格: {params.get('style', 'N/A')}
- 视角: {params.get('perspective', 'N/A')}
"""

    elif step_id == 2:
        # 步骤2：优化脚本
        optimize_data = step_results.get('optimize_script', {})
        if optimize_data:
            script_output = optimize_data.get('optimized_script', '')
            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**优化后脚本长度**: {len(script_output)} 字符

优化后的脚本内容请查看下方脚本输出区域。
"""

    elif step_id == 3:
        # 步骤3：生成素材图
        material_data = step_results.get('generate_material_images', {})
        if material_data:
            images = material_data.get('material_images', [])
            for img in images:
                img_path = img.get('image_path', '')
                if img_path:
                    # 支持 URL 和本地路径
                    if img_path.startswith(('http://', 'https://')) or Path(img_path).exists():
                        images_output.append(img_path)
            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**生成图片数量**: {len(images)} 张

生成的素材图片请查看下方图片区域。
"""

    elif step_id == 4:
        # 步骤4：生成分片脚本
        segments_data = step_results.get('generate_segment_scripts', {})
        if segments_data:
            segment_scripts = segments_data.get('segment_scripts', [])

            # 统计复用情况
            reuse_first_count = sum(1 for seg in segment_scripts if seg.get('first_frame_mode') == 'reuse_prev')

            # 预先计算每个分片的首尾帧编号
            frame_number = 1
            frame_map = {}  # {seg_idx: {'first': 编号, 'last': 编号}}

            for seg in segment_scripts:
                seg_idx = seg.get('index', 0)
                first_mode = seg.get('first_frame_mode', 'generate')

                frame_map[seg_idx] = {}

                # 首帧编号
                if first_mode == 'reuse_prev' and seg_idx > 0:
                    # 复用前一分片的尾帧编号
                    frame_map[seg_idx]['first'] = frame_map[seg_idx - 1]['last']
                else:
                    frame_map[seg_idx]['first'] = frame_number
                    frame_number += 1

                # 尾帧编号（总是新生成）
                frame_map[seg_idx]['last'] = frame_number
                frame_number += 1

            total_frames = frame_number - 1

            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**分片数量**: {len(segment_scripts)} 个
**预计生成帧数**: {total_frames} 张（复用 {reuse_first_count} 张）

"""
            for seg in segment_scripts:
                seg_idx = seg.get('index', 0)
                first_mode = seg.get('first_frame_mode', 'generate')
                last_mode = seg.get('last_frame_mode', 'generate')

                first_num = frame_map[seg_idx]['first']
                last_num = frame_map[seg_idx]['last']

                # 首帧显示
                if first_mode == 'reuse_prev':
                    first_text = f"**#{first_num}** 🔗复用"
                else:
                    first_text = f"**#{first_num}**"

                # 尾帧显示
                if last_mode == 'reuse_next':
                    last_text = f"**#{last_num}** 🔗被复用"
                else:
                    last_text = f"**#{last_num}**"

                output_text += f"""### 分片 {seg_idx + 1}　｜　首帧 {first_text}　尾帧 {last_text}
- **内容**: {seg.get('content', '')}
- **时长**: {seg.get('duration', 0)}秒
- **动作**: {seg.get('action', '')}
- **镜头运动**: {seg.get('camera_movement', '')}

---
"""

    elif step_id == 5:
        # 步骤5：生成首尾帧
        frames_data = step_results.get('generate_segment_frames', {})
        segments_data = step_results.get('generate_segment_scripts', {})

        if frames_data:
            frames = frames_data.get('segment_frames', [])
            segment_scripts = segments_data.get('segment_scripts', []) if segments_data else []
            generated_count = frames_data.get('generated_count', len(frames) * 2)
            reused_count = frames_data.get('reused_count', 0)

            # 复用颜色标识（用不同颜色区分复用组）
            reuse_colors = ['🔴', '🟢', '🔵', '🟡', '🟣', '🟤', '🟠', '⚪']

            # 构建复用组映射：找出哪些帧是互相复用的
            # reuse_groups: {color_index: [(seg_idx, frame_type), ...]}
            reuse_group_map = {}  # (seg_idx, frame_type) -> color_index
            color_index = 0

            for seg in segment_scripts:
                seg_idx = seg.get('index', 0)
                first_mode = seg.get('first_frame_mode', 'generate')

                # 如果首帧复用前一分片的尾帧，它们属于同一复用组
                if first_mode == 'reuse_prev' and seg_idx > 0:
                    # 分配颜色
                    current_color = color_index % len(reuse_colors)
                    # 前一分片的尾帧
                    reuse_group_map[(seg_idx - 1, 'last')] = current_color
                    # 当前分片的首帧
                    reuse_group_map[(seg_idx, 'first')] = current_color
                    color_index += 1

            # 收集所有图片并编号，添加复用颜色标识
            frame_number = 1
            reuse_legend = []  # 记录复用组说明

            for frame in frames:
                seg_idx = frame.get('segment_index', 0)
                first_path = frame.get('first_image_path', '')
                last_path = frame.get('last_image_path', '')

                # 首帧
                if first_path and (first_path.startswith(('http://', 'https://')) or Path(first_path).exists()):
                    label = f"#{frame_number} 分片{seg_idx + 1}首帧"
                    # 检查是否属于复用组
                    if (seg_idx, 'first') in reuse_group_map:
                        color_idx = reuse_group_map[(seg_idx, 'first')]
                        color = reuse_colors[color_idx]
                        label = f"{color} {label} (复用)"
                    images_output.append((first_path, label))
                    frame_number += 1

                # 尾帧
                if last_path and (last_path.startswith(('http://', 'https://')) or Path(last_path).exists()):
                    label = f"#{frame_number} 分片{seg_idx + 1}尾帧"
                    # 检查是否属于复用组
                    if (seg_idx, 'last') in reuse_group_map:
                        color_idx = reuse_group_map[(seg_idx, 'last')]
                        color = reuse_colors[color_idx]
                        label = f"{color} {label} (被复用)"
                    images_output.append((last_path, label))
                    frame_number += 1

            # 生成复用说明
            reuse_info = ""
            if reuse_group_map:
                reuse_info = "\n\n**复用关系**（相同颜色表示同一张图片）:\n"
                # 按颜色分组
                color_groups = {}
                for (seg_idx, frame_type), color_idx in reuse_group_map.items():
                    if color_idx not in color_groups:
                        color_groups[color_idx] = []
                    color_groups[color_idx].append((seg_idx, frame_type))

                for color_idx in sorted(color_groups.keys()):
                    color = reuse_colors[color_idx]
                    pairs = color_groups[color_idx]
                    # 找出复用关系
                    for seg_idx, frame_type in pairs:
                        if frame_type == 'last':
                            reuse_info += f"- {color} 分片{seg_idx + 1}尾帧 → 分片{seg_idx + 2}首帧\n"

            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**生成帧组数**: {len(frames)} 组
**实际生成**: {generated_count} 张 | **复用**: {reused_count} 张
{reuse_info}
图片按编号排列，相同颜色标识的帧是复用关系（同一张图片）。
"""

    elif step_id == 6:
        # 步骤6：生成视频
        videos_data = step_results.get('generate_videos', {})
        if videos_data:
            videos = videos_data.get('generated_videos', [])
            for video in videos:
                video_path = video.get('video_path', '')
                # 支持 URL 和本地路径
                if video_path and (video_path.startswith(('http://', 'https://')) or Path(video_path).exists()):
                    videos_output.append(video_path)
            output_text = f"""## {step_info['icon']} {step_title}

**状态**: ✅ 已完成

**生成视频数量**: {len(videos)} 个

🎉 所有视频片段已生成完成，可以下载使用！
"""

    if not output_text:
        output_text = f"## {step_info['icon']} {step_title}\n\n暂无数据"

    return (
        output_text,
        script_output,
        images_output if images_output else None,
        videos_output if videos_output else None
    )


def get_action_button_state(step_id: int, completed_steps: list[str]) -> tuple[str, bool, bool]:
    """根据当前显示的步骤和完成状态，返回操作按钮的文字、可见性和是否显示提示词输入框

    Returns:
        (button_text, is_visible, show_prompt_input)
    """
    step_info = STEPS[step_id - 1]
    step_name = step_info["name"]

    # 已完成的步骤：显示重新生成按钮和提示词输入框
    regenerate_config = {
        3: ("🔄 重新生成素材图", True),
        4: ("🔄 重新生成分片脚本", True),
        5: ("🔄 全部重新生成首尾帧", True),
        6: ("🔄 重新生成视频", True),
    }

    if step_id in regenerate_config and step_name in completed_steps:
        btn_text, show_prompt = regenerate_config[step_id]
        return btn_text, True, show_prompt

    # 其他情况：如果该步骤是下一个待执行的步骤，显示正常按钮
    next_step = get_next_step_info(completed_steps)
    if next_step and next_step["id"] == step_id:
        return f"{step_info['icon']} {step_info['title']}", True, False

    # 该步骤已完成或未到达，隐藏按钮
    return "", False, False


def switch_step_view(step_id: int):
    """切换查看的步骤"""
    visibility = get_step_component_visibility(step_id)

    if not current_session_id:
        completed_steps = []
        btn_text, btn_visible, show_prompt = get_action_button_state(step_id, completed_steps)
        return (
            gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, step_id)),
            gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, step_id)),
            gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, step_id)),
            gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, step_id)),
            gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, step_id)),
            gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, step_id)),
            "请先创建会话",
            gr.update(value="", visible=visibility["script_visible"]),
            gr.update(value=None, visible=visibility["images_visible"]),
            gr.update(value=None, visible=visibility["videos_visible"]),
            step_id,
            gr.update(value=btn_text, visible=btn_visible),
            gr.update(visible=show_prompt, value=""),  # 自定义提示词输入框
            [],  # 首尾帧数据（无会话时为空）
        )

    status = workflow.get_session_status(current_session_id)
    completed_steps = status.get('completed_steps', [])

    output_text, script_output, images_output, videos_output = load_single_step_output(current_session_id, step_id)

    # 获取操作按钮状态
    btn_text, btn_visible, show_prompt = get_action_button_state(step_id, completed_steps)

    # 加载首尾帧数据
    frames_data = load_frames_data(current_session_id)

    return (
        gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, step_id)),
        gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, step_id)),
        gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, step_id)),
        gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, step_id)),
        gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, step_id)),
        gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, step_id)),
        output_text,
        gr.update(value=script_output, visible=visibility["script_visible"]),
        gr.update(value=images_output, visible=visibility["images_visible"]),
        gr.update(value=videos_output, visible=visibility["videos_visible"]),
        step_id,
        gr.update(value=btn_text, visible=btn_visible),
        gr.update(visible=show_prompt, value=""),  # 自定义提示词输入框
        frames_data,  # 首尾帧数据
    )


def get_current_state():
    """获取当前状态，返回所有UI组件的更新"""
    if not current_session_id:
        return {
            "session_info": "还没有活动会话",
            "status_text": "会话状态: 无",
            "guide_text": "请点击【创建新会话】开始视频创作流程",
            "new_session_enabled": True,
            "next_step_enabled": False,
            "next_step_text": "下一步",
            "script_interactive": False,
            "params_interactive": False,
        }

    status = workflow.get_session_status(current_session_id)
    completed_steps = status.get('completed_steps', [])
    next_step = get_next_step_info(completed_steps)

    session_info = format_session_info(current_session_id, status)

    if not next_step:
        return {
            "session_info": session_info,
            "status_text": "会话状态: 已完成",
            "guide_text": "恭喜！视频创作流程已全部完成，你可以查看和下载生成的视频。",
            "new_session_enabled": True,
            "next_step_enabled": False,
            "next_step_text": "已完成",
            "script_interactive": False,
            "params_interactive": False,
        }

    # 确定各个输入框是否可交互
    # 步骤1时脚本和参数都可编辑，步骤1完成后都锁定
    script_interactive = next_step["id"] == 1
    params_interactive = next_step["id"] == 1

    # 生成引导文本
    guide_text = f"准备执行：{next_step['icon']} {next_step['title']}"
    if next_step["id"] == 1:
        guide_text += "\n\n请输入视频脚本并选择参数，然后点击【下一步】提交"
    else:
        guide_text += "\n\n点击【下一步】继续执行"

    return {
        "session_info": session_info,
        "status_text": f"会话状态: 进行中 ({status['progress']})",
        "guide_text": guide_text,
        "new_session_enabled": True,
        "next_step_enabled": True,
        "next_step_text": f"{next_step['icon']} {next_step['title']}",
        "script_interactive": script_interactive,
        "params_interactive": params_interactive,
    }


def load_latest_session():
    """加载最近的活动会话"""
    global current_session_id
    logger.info("尝试加载最近的活动会话...")

    session_id = workflow.session_manager.get_latest_session()
    if session_id:
        current_session_id = session_id
        logger.info(f"已加载会话: {current_session_id}")

        state = get_current_state()
        script, resolution, aspect_ratio, language, style, perspective = load_session_data(session_id)

        # 获取当前步骤（显示当前/下一个待执行的步骤）
        status = workflow.get_session_status(session_id)
        completed_steps = status.get('completed_steps', [])
        next_step = get_next_step_info(completed_steps)
        current_step_id = next_step["id"] if next_step else 6  # 如果全部完成，显示最后一步

        # 加载当前步骤的输出内容
        output_text, script_output, images_output, videos_output = load_single_step_output(session_id, current_step_id)

        # 加载分片和帧数据
        segments_data = load_segments_data(session_id)
        frames_data = load_frames_data(session_id)

        # 获取当前步骤的组件可见性
        visibility = get_step_component_visibility(current_step_id)

        # 获取当前步骤的按钮状态
        btn_text, btn_visible, show_prompt = get_action_button_state(current_step_id, completed_steps)

        return (
            # 6个步骤按钮的更新
            gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, current_step_id)),
            gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, current_step_id)),
            gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, current_step_id)),
            gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, current_step_id)),
            gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, current_step_id)),
            gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, current_step_id)),
            state["session_info"],
            state["status_text"],
            state["guide_text"],
            gr.update(interactive=state["new_session_enabled"]),
            gr.update(value=btn_text, visible=btn_visible),
            gr.update(visible=show_prompt, value=""),  # 自定义提示词输入框
            gr.update(interactive=state["script_interactive"], value=script),
            gr.update(interactive=state["params_interactive"], value=resolution),
            gr.update(interactive=state["params_interactive"], value=aspect_ratio),
            gr.update(interactive=state["params_interactive"], value=language),
            gr.update(interactive=state["params_interactive"], value=style),
            gr.update(interactive=state["params_interactive"], value=perspective),
            output_text,
            gr.update(value=script_output, visible=visibility["script_visible"]),
            gr.update(value=images_output, visible=visibility["images_visible"]),
            gr.update(value=videos_output, visible=visibility["videos_visible"]),
            segments_data,
            frames_data,
            current_step_id,  # 当前选中的步骤
            get_logs(),  # 日志内容
        )
    else:
        logger.info("没有找到活动会话")
        state = get_current_state()
        completed_steps = []

        # 无会话时按钮不显示
        btn_text, btn_visible, show_prompt = "", False, False

        return (
            # 6个步骤按钮的更新
            gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, 1)),
            gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, 1)),
            gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, 1)),
            gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, 1)),
            gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, 1)),
            gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, 1)),
            state["session_info"],
            state["status_text"],
            state["guide_text"],
            gr.update(interactive=state["new_session_enabled"]),
            gr.update(value=btn_text, visible=btn_visible),
            gr.update(visible=show_prompt, value=""),  # 自定义提示词输入框
            gr.update(interactive=state["script_interactive"], value=""),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            "## 📝 提交脚本和参数\n\n**状态**: 等待执行\n\n请输入视频脚本并选择参数，然后点击【下一步】提交",
            gr.update(value="", visible=False),  # 脚本输出 - 步骤1时隐藏
            gr.update(value=None, visible=False),  # 图片 - 步骤1时隐藏
            gr.update(value=None, visible=False),  # 视频 - 步骤1时隐藏
            [],
            [],
            1,  # 默认选中步骤1
            "",  # 空日志
        )


def create_new_session():
    """创建新会话"""
    global current_session_id
    logger.info("用户请求创建新会话")

    # 清空日志缓冲区
    clear_logs()

    current_session_id = workflow.create_session()
    logger.info(f"新会话创建成功: {current_session_id}")

    state = get_current_state()
    completed_steps = []

    # 获取步骤1的按钮状态
    btn_text, btn_visible, show_prompt = get_action_button_state(1, completed_steps)

    return (
        # 6个步骤按钮的更新
        gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, 1)),
        gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, 1)),
        gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, 1)),
        gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, 1)),
        gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, 1)),
        gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, 1)),
        state["session_info"],
        state["status_text"],
        state["guide_text"],
        gr.update(interactive=state["new_session_enabled"]),
        gr.update(value=btn_text, visible=btn_visible),
        gr.update(visible=show_prompt, value=""),  # 自定义提示词输入框
        gr.update(interactive=state["script_interactive"], value=""),
        gr.update(interactive=state["params_interactive"], value="1080p"),
        gr.update(interactive=state["params_interactive"], value="16:9"),
        gr.update(interactive=state["params_interactive"], value="zh-CN"),
        gr.update(interactive=state["params_interactive"], value="cinematic"),
        gr.update(interactive=state["params_interactive"], value="third_person"),
        "## 📝 提交脚本和参数\n\n**状态**: 等待执行\n\n请输入视频脚本并选择参数，然后点击【下一步】提交",  # 输出文本
        gr.update(value="", visible=False),  # 脚本输出 - 步骤1时隐藏
        gr.update(value=None, visible=False),  # 图片 - 步骤1时隐藏
        gr.update(value=None, visible=False),  # 视频 - 步骤1时隐藏
        [],  # 分片状态
        [],  # 帧状态
        1,  # 当前选中步骤1
        get_logs(),  # 日志内容
    )


def _generate_step_button_updates(completed_steps: list[str], selected_step: int):
    """生成6个步骤按钮的更新"""
    return (
        gr.update(value=get_step_button_label(1, completed_steps), variant=get_step_button_style(1, completed_steps, selected_step)),
        gr.update(value=get_step_button_label(2, completed_steps), variant=get_step_button_style(2, completed_steps, selected_step)),
        gr.update(value=get_step_button_label(3, completed_steps), variant=get_step_button_style(3, completed_steps, selected_step)),
        gr.update(value=get_step_button_label(4, completed_steps), variant=get_step_button_style(4, completed_steps, selected_step)),
        gr.update(value=get_step_button_label(5, completed_steps), variant=get_step_button_style(5, completed_steps, selected_step)),
        gr.update(value=get_step_button_label(6, completed_steps), variant=get_step_button_style(6, completed_steps, selected_step)),
    )


async def execute_next_step(
    script: str,
    resolution: str,
    aspect_ratio: str,
    language: str,
    style: str,
    perspective: str,
    current_display_step: int = 0,
    custom_prompt: str = ""
):
    """执行下一步或重新生成

    Args:
        current_display_step: 当前显示的步骤ID，用于判断是否是重新生成操作
        custom_prompt: 自定义提示词，用于重新生成时增加控制力
    """
    if not current_session_id:
        logger.error("没有活动会话")
        state = get_current_state()
        completed_steps = []
        return (
            *_generate_step_button_updates(completed_steps, 1),
            state["session_info"],
            state["status_text"],
            state["guide_text"],
            gr.update(interactive=state["new_session_enabled"]),
            gr.update(value="", visible=False),  # 操作按钮
            gr.update(visible=False, value=""),  # 自定义提示词
            gr.update(interactive=state["script_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            "请先创建会话",
            gr.update(value="", visible=False),
            gr.update(value=None, visible=False),
            gr.update(value=None, visible=False),
            [],
            [],
            1,
            get_logs(),
        )

    status = workflow.get_session_status(current_session_id)
    completed_steps = status.get('completed_steps', [])
    next_step = get_next_step_info(completed_steps)

    # 检查是否是重新生成操作（步骤3、4、5、6）
    regenerate_step_map = {
        3: "generate_material_images",
        4: "generate_segment_scripts",
        5: "generate_segment_frames",
        6: "generate_videos",
    }

    is_regenerate = False
    regenerate_step_id = None

    if current_display_step in regenerate_step_map:
        step_name = regenerate_step_map[current_display_step]
        if step_name in completed_steps:
            is_regenerate = True
            regenerate_step_id = current_display_step
            logger.info(f"执行步骤{current_display_step}重新生成，自定义提示词: {custom_prompt[:50] if custom_prompt else '无'}...")

            # ⚠️ 重要：清空后续依赖步骤的数据
            logger.info(f"清空步骤{current_display_step}之后的所有步骤数据...")
            workflow.session_manager.clear_steps_after(current_session_id, step_name)

            next_step = STEPS[current_display_step - 1]

    if not next_step:
        state = get_current_state()
        segments_data = load_segments_data(current_session_id)
        frames_data = load_frames_data(current_session_id)
        # 全部完成，显示最后一步的内容
        output_text, script_output, images_output, videos_output = load_single_step_output(current_session_id, 6)
        visibility = get_step_component_visibility(6)
        # 获取步骤6的按钮状态
        btn_text, btn_visible, show_prompt = get_action_button_state(6, completed_steps)
        return (
            *_generate_step_button_updates(completed_steps, 6),
            state["session_info"],
            state["status_text"],
            state["guide_text"],
            gr.update(interactive=state["new_session_enabled"]),
            gr.update(value=btn_text, visible=btn_visible),
            gr.update(visible=show_prompt, value=""),  # 自定义提示词
            gr.update(interactive=state["script_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            gr.update(interactive=state["params_interactive"]),
            output_text,
            gr.update(value=script_output, visible=visibility["script_visible"]),
            gr.update(value=images_output, visible=visibility["images_visible"]),
            gr.update(value=videos_output, visible=visibility["videos_visible"]),
            segments_data,
            frames_data,
            6,
            get_logs(),
        )

    executing_step_id = next_step["id"]
    logger.info(f"执行步骤 {executing_step_id}: {next_step['name']}")

    result = None

    # 根据步骤ID执行相应操作
    if next_step["id"] == 1:
        # 步骤1：提交脚本和参数
        if not script.strip():
            state = get_current_state()
            btn_text, btn_visible, show_prompt = get_action_button_state(1, completed_steps)
            return (
                *_generate_step_button_updates(completed_steps, 1),
                state["session_info"],
                state["status_text"],
                state["guide_text"],
                gr.update(interactive=state["new_session_enabled"]),
                gr.update(value=btn_text, visible=btn_visible),
                gr.update(visible=show_prompt, value=""),  # 自定义提示词
                gr.update(interactive=state["script_interactive"]),
                gr.update(interactive=state["params_interactive"]),
                gr.update(interactive=state["params_interactive"]),
                gr.update(interactive=state["params_interactive"]),
                gr.update(interactive=state["params_interactive"]),
                gr.update(interactive=state["params_interactive"]),
                "## ⚠️ 错误\n\n请输入脚本内容",
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                [],
                [],
                1,
                get_logs(),
            )
        video_params = {
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "language": language,
            "style": style,
            "perspective": perspective,
        }
        result = workflow.step_submit(current_session_id, script, video_params)

    elif next_step["id"] == 2:
        result = await workflow.step_optimize_script(current_session_id)

    elif next_step["id"] == 3:
        # 传递自定义提示词（仅在重新生成时有效）
        extra_prompt = custom_prompt if is_regenerate else ""
        result = await workflow.step_generate_material_images(current_session_id, extra_prompt=extra_prompt)

    elif next_step["id"] == 4:
        # 传递自定义提示词（仅在重新生成时有效）
        extra_prompt = custom_prompt if is_regenerate else ""
        result = await workflow.step_generate_segment_scripts(current_session_id, extra_prompt=extra_prompt)

    elif next_step["id"] == 5:
        # 传递自定义提示词（仅在重新生成时有效）
        extra_prompt = custom_prompt if is_regenerate else ""
        result = await workflow.step_generate_segment_frames(current_session_id, extra_prompt=extra_prompt)

    elif next_step["id"] == 6:
        # 传递自定义提示词（仅在重新生成时有效）
        extra_prompt = custom_prompt if is_regenerate else ""
        result = await workflow.step_generate_videos(current_session_id, extra_prompt=extra_prompt)

    # 处理执行结果
    if not result or not result["success"]:
        error_msg = result["error"] if result else "未知错误"
        logger.error(f"步骤 {executing_step_id} 执行失败: {error_msg}")
        output_text = f"## ❌ 步骤 {executing_step_id} 执行失败\n\n**错误**: {error_msg}"
        script_output = ""
        images_output = None
        videos_output = None
    else:
        logger.info(f"步骤 {executing_step_id} 执行成功")
        # 执行成功后，加载该步骤的输出（显示当前步骤的结果，而不是下一步）
        output_text, script_output, images_output, videos_output = load_single_step_output(current_session_id, executing_step_id)

    # 加载分片和帧状态
    segments_data = load_segments_data(current_session_id)
    frames_data = load_frames_data(current_session_id)

    # 更新状态
    state = get_current_state()
    new_status = workflow.get_session_status(current_session_id)
    new_completed_steps = new_status.get('completed_steps', [])

    # 执行完成后，显示当前执行的步骤（而不是下一步），让用户看到执行结果
    display_step_id = executing_step_id
    visibility = get_step_component_visibility(display_step_id)

    # 根据当前显示步骤获取按钮状态（关键修复：使用 display_step_id 而不是下一步）
    btn_text, btn_visible, show_prompt = get_action_button_state(display_step_id, new_completed_steps)

    return (
        *_generate_step_button_updates(new_completed_steps, display_step_id),
        state["session_info"],
        state["status_text"],
        state["guide_text"],
        gr.update(interactive=state["new_session_enabled"]),
        gr.update(value=btn_text, visible=btn_visible),
        gr.update(visible=show_prompt, value=""),  # 自定义提示词
        gr.update(interactive=state["script_interactive"]),
        gr.update(interactive=state["params_interactive"]),
        gr.update(interactive=state["params_interactive"]),
        gr.update(interactive=state["params_interactive"]),
        gr.update(interactive=state["params_interactive"]),
        gr.update(interactive=state["params_interactive"]),
        output_text,
        gr.update(value=script_output, visible=visibility["script_visible"]),
        gr.update(value=images_output, visible=visibility["images_visible"]),
        gr.update(value=videos_output, visible=visibility["videos_visible"]),
        segments_data,
        frames_data,
        display_step_id,
        get_logs(),
    )


# ==================== 分片脚本编辑相关函数 ====================

def load_segments_data(session_id: str) -> list[dict]:
    """加载分片脚本数据"""
    if not session_id:
        return []

    status = workflow.get_session_status(session_id)
    step_results = status.get('step_results', {})
    segments_data = step_results.get('generate_segment_scripts', {})

    if not segments_data:
        return []

    return segments_data.get('segment_scripts', [])


def save_segment_edit(
    segment_index: int,
    content: str,
    duration: float,
    action: str,
    camera_movement: str,
    composition: str,
    atmosphere: str
):
    """保存分片编辑"""
    if not current_session_id:
        return "请先创建会话"

    segment_data = {
        "index": segment_index,
        "content": content,
        "duration": duration,
        "action": action,
        "camera_movement": camera_movement,
        "composition": composition,
        "atmosphere": atmosphere,
        "focus": "",
        "transition": "",
    }

    result = workflow.update_segment(current_session_id, segment_index, segment_data)

    if result["success"]:
        return f"分片 {segment_index + 1} 已保存"
    else:
        return f"保存失败: {result.get('error', '未知错误')}"


def delete_segment_action(segment_index: int):
    """删除分片"""
    if not current_session_id:
        return "请先创建会话", []

    result = workflow.delete_segment(current_session_id, segment_index)

    if result["success"]:
        # 重新加载分片数据
        segments = load_segments_data(current_session_id)
        return f"分片 {segment_index + 1} 已删除", segments
    else:
        segments = load_segments_data(current_session_id)
        return f"删除失败: {result.get('error', '未知错误')}", segments


def add_segment_action():
    """新增分片"""
    if not current_session_id:
        return "请先创建会话", []

    new_segment = {
        "content": "新分片内容（请编辑）",
        "duration": 5.0,
        "action": "",
        "camera_movement": "static",
        "composition": "",
        "atmosphere": "",
        "focus": "",
        "transition": "",
    }

    result = workflow.add_segment(current_session_id, new_segment)

    if result["success"]:
        segments = load_segments_data(current_session_id)
        return "新分片已添加", segments
    else:
        segments = load_segments_data(current_session_id)
        return f"添加失败: {result.get('error', '未知错误')}", segments


# ==================== 首尾帧管理相关函数 ====================

def load_frames_data(session_id: str) -> list[dict]:
    """加载首尾帧数据"""
    if not session_id:
        return []

    status = workflow.get_session_status(session_id)
    step_results = status.get('step_results', {})
    frames_data = step_results.get('generate_segment_frames', {})

    if not frames_data:
        return []

    return frames_data.get('segment_frames', [])


def upload_frame_action(segment_index: int, frame_type: str, file):
    """上传替换帧"""
    if not current_session_id:
        return "请先创建会话", []

    if file is None:
        return "请选择文件", load_frames_data(current_session_id)

    # file 是 NamedString 或文件路径
    file_path = file.name if hasattr(file, 'name') else str(file)

    result = workflow.replace_frame(current_session_id, segment_index, frame_type, file_path)

    frames = load_frames_data(current_session_id)

    if result["success"]:
        message = result["message"]
        # 如果步骤已完成，在消息中提示用户
        if result.get("step_completed"):
            message += " ✅ 所有首尾帧已完成！请点击步骤按钮刷新界面。"
        return message, frames
    else:
        return f"上传失败: {result.get('error', '未知错误')}", frames


async def regenerate_frame_action(segment_index: int, frame_type: str, custom_prompt: str = ""):
    """重新生成帧

    Args:
        segment_index: 分片索引
        frame_type: 帧类型 ("first" 或 "last")
        custom_prompt: 自定义提示词，为空则由LLM自动生成
    """
    if not current_session_id:
        return "请先创建会话", []

    result = await workflow.regenerate_frame(
        current_session_id, segment_index, frame_type, custom_prompt
    )

    frames = load_frames_data(current_session_id)

    if result["success"]:
        message = result["message"]
        # 如果步骤已完成，在消息中提示用户
        if result.get("step_completed"):
            message += " ✅ 所有首尾帧已完成！请点击步骤按钮刷新界面。"
        return message, frames
    else:
        return f"重新生成失败: {result.get('error', '未知错误')}", frames


def reuse_adjacent_frame_action(segment_index: int, frame_type: str):
    """复用相邻分片的帧

    - 首帧: 复用上一分片的尾帧
    - 尾帧: 复用下一分片的首帧
    """
    if not current_session_id:
        return "请先创建会话", []

    result = workflow.reuse_adjacent_frame(current_session_id, segment_index, frame_type)

    frames = load_frames_data(current_session_id)

    if result["success"]:
        message = result["message"]
        # 如果步骤已完成，在消息中提示用户
        if result.get("step_completed"):
            message += " ✅ 所有首尾帧已完成！请点击步骤按钮刷新界面。"
        return message, frames
    else:
        return f"复用失败: {result.get('error', '未知错误')}", frames


def create_ui():
    """创建Gradio界面"""
    with gr.Blocks(title="AI视频创作智能体 V2") as app:
        with gr.Row():
            with gr.Column(scale=4):
                gr.Markdown("""
# AI视频创作智能体 V2

符合PRD的6步流程：提交脚本和参数 → 优化脚本 → 生成素材图 → 生成分片脚本 → 生成首尾帧 → 生成视频

每次启动自动恢复上次会话，点击【创建新会话】开始新流程
                """)
            with gr.Column(scale=1, min_width=150):
                new_session_btn = gr.Button("创建新会话", variant="secondary", size="lg")

        # 步骤导航条 - 点击步骤可查看详情
        gr.HTML(generate_step_button_css())
        gr.Markdown("### 流程步骤（点击查看详情）")
        with gr.Row():
            step_btn_1 = gr.Button("📝 提交脚本和参数", size="sm", variant="primary")
            step_btn_2 = gr.Button("✨ 优化脚本", size="sm", variant="secondary")
            step_btn_3 = gr.Button("🖼️ 生成素材图", size="sm", variant="secondary")
            step_btn_4 = gr.Button("📋 生成分片脚本", size="sm", variant="secondary")
            step_btn_5 = gr.Button("🎬 生成首尾帧", size="sm", variant="secondary")
            step_btn_6 = gr.Button("🎥 生成视频", size="sm", variant="secondary")

        # 当前选中的步骤ID状态
        current_step_state = gr.State(1)

        with gr.Row():
            with gr.Column(scale=1):
                session_info = gr.Markdown("还没有活动会话")
            with gr.Column(scale=1):
                status_text = gr.Markdown("会话状态: 无")

        guide_text = gr.Markdown("正在加载...")

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 视频脚本")

                script_input = gr.Textbox(
                    label="视频脚本内容",
                    placeholder="请输入您的视频脚本...",
                    lines=8,
                    interactive=False
                )

                gr.Markdown("### 视频参数")

                with gr.Row():
                    resolution = gr.Dropdown(
                        choices=RESOLUTION_OPTIONS,
                        value="1080p",
                        label="分辨率",
                        interactive=False
                    )
                    aspect_ratio = gr.Dropdown(
                        choices=ASPECT_RATIO_OPTIONS,
                        value="16:9",
                        label="宽高比",
                        interactive=False
                    )

                with gr.Row():
                    language = gr.Dropdown(
                        choices=LANGUAGE_OPTIONS,
                        value="zh-CN",
                        label="语言",
                        interactive=False
                    )
                    style = gr.Dropdown(
                        choices=STYLE_OPTIONS,
                        value="cinematic",
                        label="美学风格",
                        interactive=False
                    )

                perspective = gr.Dropdown(
                    choices=PERSPECTIVE_OPTIONS,
                    value="third_person",
                    label="视角",
                    interactive=False
                )

                gr.Markdown("### 执行步骤")

                # 自定义提示词输入框（重新生成时显示）
                custom_prompt_input = gr.Textbox(
                    label="自定义提示词（可选）",
                    placeholder="输入额外的提示词来控制重新生成的效果，例如：\n- 素材图：更鲜艳的颜色、卡通风格\n- 分片脚本：更多动作细节、慢镜头\n- 首尾帧：黄昏光线、俯拍角度\n- 视频：流畅过渡、电影感",
                    lines=2,
                    visible=False
                )

                next_step_btn = gr.Button(
                    "下一步",
                    variant="primary",
                    size="lg",
                    visible=False
                )

            with gr.Column(scale=2):
                gr.Markdown("### 当前步骤详情")

                output_text = gr.Markdown("等待开始...")

                script_output = gr.Textbox(
                    label="优化后的脚本",
                    lines=10,
                    visible=False,
                    interactive=False
                )

                with gr.Group():
                    images_gallery = gr.Gallery(
                        label="生成的图片",
                        visible=False,
                        columns=3,
                        height="auto"
                    )

                videos_output = gr.Files(
                    label="生成的视频",
                    visible=False
                )

                # 执行日志显示区域
                with gr.Accordion("执行日志", open=False):
                    log_output = gr.Textbox(
                        label="",
                        lines=15,
                        max_lines=30,
                        interactive=False,
                        show_label=False,
                        placeholder="执行日志将在此显示..."
                    )
                    refresh_log_btn = gr.Button("刷新日志", size="sm", variant="secondary")

        # ==================== 分片脚本编辑区域 ====================
        with gr.Accordion("分片脚本编辑", open=False, visible=True) as segment_edit_accordion:
            gr.Markdown("**提示**: 步骤4完成后可在此编辑分片脚本。修改后记得点击保存。")

            # 状态：存储当前分片数据
            segments_state = gr.State([])

            # 编辑提示信息
            segment_edit_status = gr.Markdown("")

            # 新增分片按钮
            add_segment_btn = gr.Button("+ 新增分片", variant="secondary", size="sm")

            # 使用@gr.render动态渲染分片编辑表单
            @gr.render(inputs=[segments_state])
            def render_segment_editors(segments_list):
                if not segments_list:
                    gr.Markdown("*暂无分片数据，请先执行步骤4*")
                    return

                for seg in segments_list:
                    seg_idx = seg.get('index', 0)
                    with gr.Accordion(f"分片 {seg_idx + 1}", open=False):
                        with gr.Group():
                            content_input = gr.Textbox(
                                label="内容",
                                value=seg.get('content', ''),
                                lines=3
                            )
                            with gr.Row():
                                duration_input = gr.Slider(
                                    label="时长（秒）",
                                    minimum=1,
                                    maximum=8,
                                    step=0.5,
                                    value=seg.get('duration', 5.0)
                                )
                                camera_input = gr.Dropdown(
                                    label="镜头运动",
                                    choices=CAMERA_MOVEMENT_OPTIONS,
                                    value=seg.get('camera_movement', 'static'),
                                    allow_custom_value=True
                                )
                            action_input = gr.Textbox(
                                label="动作",
                                value=seg.get('action', ''),
                                lines=1
                            )
                            with gr.Row():
                                composition_input = gr.Textbox(
                                    label="构图",
                                    value=seg.get('composition', ''),
                                    lines=1
                                )
                                atmosphere_input = gr.Textbox(
                                    label="氛围",
                                    value=seg.get('atmosphere', ''),
                                    lines=1
                                )
                            with gr.Row():
                                save_btn = gr.Button(f"保存修改", variant="primary", size="sm")
                                delete_btn = gr.Button(f"删除分片", variant="stop", size="sm")

                            # 保存按钮事件
                            def make_save_fn(idx):
                                def save_fn(content, duration, action, camera, composition, atmosphere):
                                    return save_segment_edit(idx, content, duration, action, camera, composition, atmosphere)
                                return save_fn

                            save_btn.click(
                                fn=make_save_fn(seg_idx),
                                inputs=[content_input, duration_input, action_input, camera_input, composition_input, atmosphere_input],
                                outputs=[segment_edit_status]
                            )

                            # 删除按钮事件
                            def make_delete_fn(idx):
                                def delete_fn():
                                    return delete_segment_action(idx)
                                return delete_fn

                            delete_btn.click(
                                fn=make_delete_fn(seg_idx),
                                outputs=[segment_edit_status, segments_state]
                            )

            # 新增分片按钮事件
            add_segment_btn.click(
                fn=add_segment_action,
                outputs=[segment_edit_status, segments_state]
            )

        # ==================== 首尾帧管理区域 ====================
        with gr.Accordion("首尾帧管理", open=False, visible=True) as frame_manage_accordion:
            gr.Markdown("""**提示**: 步骤5完成后可在此管理首尾帧。
- **复用**: 直接使用相邻分片的帧，保持画面连贯
- **重新生成**: 基于当前分片脚本和上下文重新生成
- **上传替换**: 上传自定义图片替换""")

            # 状态：存储当前帧数据
            frames_state = gr.State([])

            # 编辑提示信息
            frame_edit_status = gr.Markdown("")

            # 使用@gr.render动态渲染帧管理表单
            @gr.render(inputs=[frames_state])
            def render_frame_managers(frames_list):
                if not frames_list:
                    gr.Markdown("*暂无首尾帧数据，请先执行步骤5*")
                    return

                total_segments = len(frames_list)

                for frame in frames_list:
                    seg_idx = frame.get('segment_index', 0)
                    first_path = frame.get('first_image_path', '')
                    last_path = frame.get('last_image_path', '')

                    # 判断路径是否有效（URL 或存在的本地文件）
                    first_valid = first_path and (first_path.startswith(('http://', 'https://')) or Path(first_path).exists())
                    last_valid = last_path and (last_path.startswith(('http://', 'https://')) or Path(last_path).exists())

                    # 判断是否可以复用相邻帧
                    can_reuse_prev = seg_idx > 0  # 不是第一个分片，可以复用上一分片尾帧
                    can_reuse_next = seg_idx < total_segments - 1  # 不是最后一个分片，可以复用下一分片首帧

                    with gr.Accordion(f"分片 {seg_idx + 1} 首尾帧", open=False):
                        with gr.Row():
                            # ========== 首帧区域 ==========
                            with gr.Column():
                                gr.Markdown("**首帧**")
                                if first_valid:
                                    gr.Image(value=first_path, label=f"首帧", height=200)
                                else:
                                    gr.Markdown("*首帧未生成*")

                                # 自定义提示词输入框
                                first_prompt_input = gr.Textbox(
                                    label="自定义提示词（可选）",
                                    placeholder="留空则由AI自动生成提示词",
                                    lines=2
                                )

                                # 复用按钮（如果不是第一个分片）
                                if can_reuse_prev:
                                    first_reuse_btn = gr.Button(
                                        f"📎 复用分片{seg_idx}尾帧",
                                        size="sm",
                                        variant="secondary"
                                    )

                                # 重新生成按钮
                                first_regen_btn = gr.Button("🔄 重新生成首帧", size="sm")

                                # 上传替换
                                first_upload = gr.File(
                                    label="📤 上传替换",
                                    file_types=["image"],
                                    file_count="single"
                                )

                            # ========== 尾帧区域 ==========
                            with gr.Column():
                                gr.Markdown("**尾帧**")
                                if last_valid:
                                    gr.Image(value=last_path, label=f"尾帧", height=200)
                                else:
                                    gr.Markdown("*尾帧未生成*")

                                # 自定义提示词输入框
                                last_prompt_input = gr.Textbox(
                                    label="自定义提示词（可选）",
                                    placeholder="留空则由AI自动生成提示词",
                                    lines=2
                                )

                                # 复用按钮（如果不是最后一个分片）
                                if can_reuse_next:
                                    last_reuse_btn = gr.Button(
                                        f"📎 复用分片{seg_idx + 2}首帧",
                                        size="sm",
                                        variant="secondary"
                                    )

                                # 重新生成按钮
                                last_regen_btn = gr.Button("🔄 重新生成尾帧", size="sm")

                                # 上传替换
                                last_upload = gr.File(
                                    label="📤 上传替换",
                                    file_types=["image"],
                                    file_count="single"
                                )

                        # ========== 事件绑定 ==========

                        # 首帧复用事件
                        if can_reuse_prev:
                            def make_reuse_first_fn(idx):
                                def reuse_fn():
                                    return reuse_adjacent_frame_action(idx, "first")
                                return reuse_fn

                            first_reuse_btn.click(
                                fn=make_reuse_first_fn(seg_idx),
                                outputs=[frame_edit_status, frames_state]
                            )

                        # 首帧上传事件
                        def make_upload_first_fn(idx):
                            def upload_fn(file):
                                return upload_frame_action(idx, "first", file)
                            return upload_fn

                        first_upload.change(
                            fn=make_upload_first_fn(seg_idx),
                            inputs=[first_upload],
                            outputs=[frame_edit_status, frames_state]
                        )

                        # 首帧重新生成事件
                        def make_regen_first_fn(idx):
                            async def regen_fn(custom_prompt):
                                try:
                                    result = await regenerate_frame_action(idx, "first", custom_prompt)
                                    # 返回结果 + 恢复按钮状态
                                    return result[0], result[1], gr.update(value="🔄 重新生成首帧", interactive=True)
                                except Exception as e:
                                    # 发生异常时也要恢复按钮状态
                                    frames = load_frames_data(current_session_id) if current_session_id else []
                                    return f"生成失败: {str(e)}", frames, gr.update(value="🔄 重新生成首帧", interactive=True)
                            return regen_fn

                        first_regen_btn.click(
                            fn=lambda: gr.update(value="⏳ 生成中...", interactive=False),
                            outputs=[first_regen_btn]
                        ).then(
                            fn=make_regen_first_fn(seg_idx),
                            inputs=[first_prompt_input],
                            outputs=[frame_edit_status, frames_state, first_regen_btn]
                        )

                        # 尾帧复用事件
                        if can_reuse_next:
                            def make_reuse_last_fn(idx):
                                def reuse_fn():
                                    return reuse_adjacent_frame_action(idx, "last")
                                return reuse_fn

                            last_reuse_btn.click(
                                fn=make_reuse_last_fn(seg_idx),
                                outputs=[frame_edit_status, frames_state]
                            )

                        # 尾帧上传事件
                        def make_upload_last_fn(idx):
                            def upload_fn(file):
                                return upload_frame_action(idx, "last", file)
                            return upload_fn

                        last_upload.change(
                            fn=make_upload_last_fn(seg_idx),
                            inputs=[last_upload],
                            outputs=[frame_edit_status, frames_state]
                        )

                        # 尾帧重新生成事件
                        def make_regen_last_fn(idx):
                            async def regen_fn(custom_prompt):
                                try:
                                    result = await regenerate_frame_action(idx, "last", custom_prompt)
                                    # 返回结果 + 恢复按钮状态
                                    return result[0], result[1], gr.update(value="🔄 重新生成尾帧", interactive=True)
                                except Exception as e:
                                    # 发生异常时也要恢复按钮状态
                                    frames = load_frames_data(current_session_id) if current_session_id else []
                                    return f"生成失败: {str(e)}", frames, gr.update(value="🔄 重新生成尾帧", interactive=True)
                            return regen_fn

                        last_regen_btn.click(
                            fn=lambda: gr.update(value="⏳ 生成中...", interactive=False),
                            outputs=[last_regen_btn]
                        ).then(
                            fn=make_regen_last_fn(seg_idx),
                            inputs=[last_prompt_input],
                            outputs=[frame_edit_status, frames_state, last_regen_btn]
                        )

        # 主输出列表（6个步骤按钮 + 其他组件）
        main_outputs = [
            step_btn_1, step_btn_2, step_btn_3, step_btn_4, step_btn_5, step_btn_6,
            session_info, status_text, guide_text,
            new_session_btn, next_step_btn, custom_prompt_input,
            script_input, resolution, aspect_ratio, language, style, perspective,
            output_text, script_output, images_gallery, videos_output,
            segments_state, frames_state,
            current_step_state, log_output
        ]

        # 应用加载时自动恢复会话
        app.load(fn=load_latest_session, outputs=main_outputs)

        # 事件绑定
        new_session_btn.click(fn=create_new_session, outputs=main_outputs)

        next_step_btn.click(
            fn=execute_next_step,
            inputs=[script_input, resolution, aspect_ratio, language, style, perspective, current_step_state, custom_prompt_input],
            outputs=main_outputs
        )

        # 步骤切换按钮事件 - 输出包括6个步骤按钮的更新、操作按钮、自定义提示词输入框和首尾帧状态
        step_outputs = [
            step_btn_1, step_btn_2, step_btn_3, step_btn_4, step_btn_5, step_btn_6,
            output_text, script_output, images_gallery, videos_output, current_step_state,
            next_step_btn, custom_prompt_input, frames_state
        ]

        step_btn_1.click(fn=lambda: switch_step_view(1), outputs=step_outputs)
        step_btn_2.click(fn=lambda: switch_step_view(2), outputs=step_outputs)
        step_btn_3.click(fn=lambda: switch_step_view(3), outputs=step_outputs)
        step_btn_4.click(fn=lambda: switch_step_view(4), outputs=step_outputs)
        step_btn_5.click(fn=lambda: switch_step_view(5), outputs=step_outputs)
        step_btn_6.click(fn=lambda: switch_step_view(6), outputs=step_outputs)

        # 日志刷新按钮事件
        refresh_log_btn.click(fn=get_logs, outputs=[log_output])

    return app


if __name__ == "__main__":
    logger.info("正在创建UI...")
    app = create_ui()
    logger.info("UI创建完成，正在启动服务器...")
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
