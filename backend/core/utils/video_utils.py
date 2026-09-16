"""视频处理工具函数"""
import cv2
import uuid
from pathlib import Path
from PIL import Image


def extract_last_frame(video_path: str, output_dir: str = "static/images") -> str | None:
    """提取视频的最后一个帧并保存为图片

    Args:
        video_path: 视频文件路径
        output_dir: 输出图片目录

    Returns:
        保存的图片路径，失败则返回 None
    """
    try:
        # 打开视频文件
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"无法打开视频文件: {video_path}")
            return None

        # 获取总帧数
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            print(f"视频没有帧: {video_path}")
            cap.release()
            return None

        # 定位到最后一帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)

        # 读取最后一帧
        ret, frame = cap.read()
        cap.release()

        if not ret:
            print(f"无法读取视频最后一帧: {video_path}")
            return None

        # 转换 BGR 到 RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 创建 PIL Image
        pil_image = Image.fromarray(frame_rgb)

        # 确保输出目录存在
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        image_id = str(uuid.uuid4())[:8]
        video_name = Path(video_path).stem
        output_file = output_path / f"{video_name}_snapshot_{image_id}.png"

        # 保存图片
        pil_image.save(output_file, "PNG")
        print(f"视频最后一帧已保存: {output_file}")

        return str(output_file)

    except Exception as e:
        print(f"提取视频帧失败: {e}")
        return None
