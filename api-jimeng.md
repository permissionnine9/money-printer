## 即梦首尾帧生成视频请求
curl --location --request POST 'https://router.shengsuanyun.com/api/v1/tasks/generations' \
--header 'Authorization: Bearer <token>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "bytedance/jimeng_i2v_first_tail_v30",
    "image_urls": [
        "https://example.com/start.jpg",
        "https://example.com/end.jpg"
    ],
    "prompt": "视频生成提示词",
    "seed": -1, //随机种子，作为确定扩散初始状态的基础，默认-1（随机）
    "aspect_ratio":"16:9" //aspect_ratio 生成视频的长宽比（仅文生视频模式使用）枚举值: 16:9 4:3 1:1 3:4 9:16 21:9; 默认值: 16:9
    "frames": 121 //生成的总帧数（帧数 = 24 * n + 1，其中n为秒数，支持5s、10s）枚举值:121、241；默认值:121
}'

## 即梦首尾帧生成视频response
{
    "code": "success",
    "message": "",
    "data": {
        "request_id": "jimeng_20250912103041325320000CFVslBwb",
        "task_id": "",
        "action": "VIDEO_GENERATION",
        "status": "SUBMITTING",
        "fail_reason": "",
        "submit_time": 1756470641,
        "start_time": 0,
        "finish_time": 0,
        "progress": "0%",
        "data": {}
    }
}