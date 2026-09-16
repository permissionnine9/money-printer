# 豆包 doubao-seedance-1.0-pro 使用指南

## 概述

doubao-seedance-1.0-pro 是字节跳动推出的视频生成模型，支持基于首尾帧的视频生成。相比即梦和 wan2.2，doubao-seedance 提供了更多的参数控制选项。

## 主要特性

- **首尾帧控制**: 支持首帧和尾帧图片输入
- **多分辨率支持**: 720p, 1080p, 2k, 4k
- **灵活时长**: 5秒或10秒
- **帧率选择**: 16fps 或 24fps
- **宽高比自适应**: 支持多种常见比例

## 配置方法

1. **环境变量配置**
   ```bash
   # 在 .env 文件中设置
   VIDEO_SERVICE_TYPE=doubao
   SHENGSUANYUN_API_KEY=your_api_key_here
   ```

2. **代码中使用**
   ```python
   from backend.core.services import VideoServiceDoubao

   service = VideoServiceDoubao(api_key="your_api_key")
   video = await service.generate_video_from_frames(
       segment=segment,
       first_image_url="path/to/first_frame.jpg",
       last_image_url="path/to/last_frame.jpg",
       video_params=video_params
   )
   ```

## API 参数说明

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 固定值: `bytedance/doubao-seedance-1.0-pro` |
| prompt | string | 是 | 视频生成提示词 |
| image | string | 否 | 首帧图片URL或base64编码 |
| image_role | string | 否 | 首帧角色: `first_frame` |
| image_tail | string | 否 | 尾帧图片URL或base64编码（需要首帧）|
| image_tail_role | string | 否 | 尾帧角色: `last_frame` |
| resolution | string | 否 | 分辨率: `720p`, `1080p`, `2k`, `4k` |
| duration | number | 否 | 时长: `5` 或 `10`（秒）|
| ratio | string | 否 | 宽高比: `16:9`, `9:16`, `1:1`, `3:4`, `4:3`, `21:9`, `adaptive` |
| fps | number | 否 | 帧率: `16` 或 `24` |
| camera_fixed | boolean | 否 | 是否固定摄像头 |
| watermark | boolean | 否 | 是否添加水印 |
| seed | number | 否 | 随机种子，-1表示随机 |

### 响应格式

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "task_id": "task_123456",
        "status": "COMPLETED",
        "progress": "100%",
        "data": {
            "video_urls": ["https://example.com/video.mp4"]
        }
    }
}
```

## 使用示例

### 基本使用

```python
from backend.core.services.video_service_doubao import VideoServiceDoubao
from backend.core.models import ScriptSegment, VideoParams

# 初始化服务
service = VideoServiceDoubao(api_key="your_api_key")

# 创建分片信息
segment = ScriptSegment(
    index=0,
    content="一个女子在花园中漫步",
    duration=8.0,
    action="缓慢行走",
    camera_movement="跟随镜头",
    composition="中景",
    atmosphere="温暖明亮"
)

# 视频参数
params = VideoParams(
    resolution="1080p",
    aspect_ratio="16:9",
    style="写实风格"
)

# 生成视频
result = await service.generate_video_from_frames(
    segment=segment,
    first_image_url="https://example.com/start.jpg",
    last_image_url="https://example.com/end.jpg",
    video_params=params
)
```

### 高级参数

```python
# 使用高级参数
result = await service._submit_video_task(
    prompt="高质量，电影感，平滑过渡",
    first_frame_url="start.jpg",
    last_frame_url="end.jpg",
    resolution="4k",
    duration=10,
    aspect_ratio="21:9"
)
```

## 与其他服务的对比

| 特性 | doubao-seedance | jimeng | wan2.2 |
|------|----------------|--------|--------|
| 分辨率 | 720p-4k | 720p-1080p | 720p-1080p |
| 时长 | 5s/10s | 5s/10s | 5s/10s |
| 帧率 | 16/24fps | 固定 | 固定 |
| 宽高比 | 多种+自适应 | 多种 | 多种 |
| 摄像头控制 | ✅ | ❌ | ❌ |
| 水印控制 | ✅ | ❌ | ❌ |

## 注意事项

1. **图片格式**: 支持 URL 和 base64 编码格式
2. **尾帧依赖**: 使用尾帧时必须同时提供首帧
3. **分辨率选择**: 4K 分辨率需要更长的生成时间
4. **帧率选择**: 24fps 比 16fps 更流畅，但生成时间可能更长
5. **宽高比**: 使用 `adaptive` 可以让模型自动选择最佳比例

## 错误处理

常见错误及解决方案：

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 任务失败 | 图片格式不支持 | 确保图片为常见格式（jpg/png） |
| 超时 | 生成时间过长 | 降低分辨率或时长 |
| 参数错误 | 非法参数值 | 检查参数是否在支持范围内 |

## 更新日志

- 2025-02-08: 初始版本，支持 doubao-seedance-1.0-pro 基础功能