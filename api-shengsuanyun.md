## google/veo3.1-preview 生产视频
    API_KEY="OmlJTjwvW5xt-xcnopFpD6jnHF5uVK9Tyi0ac9TNfl8geCxZeW73q16sw8Zpce8wcgks8niZoRNv-w"
    
    curl --location --request POST "https://router.shengsuanyun.com/api/v1/tasks/generations" \
      --header "Content-Type: application/json" \
      --header "Authorization: Bearer ${API_KEY}" \
      --data '{
        "aspect_ratio": "16:9",
        "duration_seconds": 8,
        "enhance_prompt": true,
        "generate_audio": true,
        "model": "google/veo3.1-preview",
        "person_generation": "allow_adult",
        "prompt": "这位女士正在接受播客采访，穿着带有标志的蓝紫色上衣，上面写着胜算云的logo，她身处一个中世纪现代风格的工作室，配有白色灯光，她讲述了使用 胜算云并搭配参考图片来制作视频的内容，标志也出现在她身后的黑色背景下有框照片\n",
        "reference_images": [
                {
                        "image": "https://oss.shengsuanyun.com/example/modelinfo/201/2025-11-25_13:48:44_input_1.png",
                        "reference_type": "ASSET"
                },
                {
                        "image": "https://oss.shengsuanyun.com/example/modelinfo/201/2025-11-25_13:48:44_input_2.png",
                        "reference_type": "ASSET"
                }
        ],
        "resolution": "720p",
        "sample_count": 1,
        "seed": -1
}'

##  google/veo3 的完整请求API 
```
/**
 * Veo视频生成请求体，google/veo3 视频生成任务请求
 */
export interface ApifoxModel {
    /**
     * 视频宽高比
     */
    aspect_ratio?: AspectRatio;
    /**
     * 视频时长（秒）
     */
    duration_seconds?: number;
    /**
     * 是否使用 Gemini 优化提示词
     */
    enhance_prompt?: boolean;
    /**
     * 是否生成音频（仅 Veo 3.0 支持）
     */
    generate_audio?: boolean;
    /**
     * 输入图片，支持 Base64 Data URL 或 Google Cloud Storage URI
     */
    image?: string;
    /**
     * 尾帧图片（仅 Veo 2.0 的首尾帧控制功能）
     */
    last_frame?: string;
    /**
     * 模型 ID
     */
    model: Model;
    /**
     * 负向提示词，描述不希望看到的内容
     */
    negative_prompt?: string;
    /**
     * 人物生成控制
     */
    person_generation?: PersonGeneration;
    /**
     * 文本提示词（文生视频必填，图生视频可选）
     */
    prompt?: string;
    /**
     * 视频分辨率（仅 Veo 3.0 支持）
     */
    resolution?: Resolution;
    /**
     * 生成视频数量
     */
    sample_count?: number;
    /**
     * 随机种子
     */
    seed?: number;
    /**
     * Google Cloud Storage 存储 URI
     */
    storage_uri?: string;
    [property: string]: any;
}

/**
 * 视频宽高比
 */
export enum AspectRatio {
    The169 = "16:9",
    The916 = "9:16",
}

/**
 * 模型 ID
 */
export enum Model {
    GoogleVeo2 = "google/veo2",
    GoogleVeo3 = "google/veo3",
}

/**
 * 人物生成控制
 */
export enum PersonGeneration {
    AllowAdult = "allow_adult",
    DontAllow = "dont_allow",
}

/**
 * 视频分辨率（仅 Veo 3.0 支持）
 */
export enum Resolution {
    The1080P = "1080p",
    The720P = "720p",
}
```

## google/veo3 完整的响应API

```
/**
 * 异步Task响应
 */
export interface ApifoxModel {
    code?: string;
    data?: 异步Task响应Data;
    message?: string;
    [property: string]: any;
}

/**
 * 异步Task响应Data
 */
export interface 异步Task响应Data {
    /**
     * 任务类型
     */
    action?: Action;
    /**
     * 任务结果数据对象
     */
    data?: 异步Task响应Result;
    /**
     * 失败原因，任务成功时为空
     */
    fail_reason?: string;
    /**
     * 任务完成时间戳（Unix 时间戳，秒），未完成时为 0
     */
    finish_time?: number;
    /**
     * 进度百分比
     */
    progress?: string;
    /**
     * 请求的唯一标识符
     */
    request_id?: string;
    /**
     * 任务开始处理时间戳（Unix 时间戳，秒）
     */
    start_time?: number;
    /**
     * 任务状态，详见任务状态说明
     */
    status?: Status;
    /**
     * 任务提交时间戳（Unix 时间戳，秒）
     */
    submit_time?: number;
    /**
     * 任务 ID，系统内部生成的任务标识符
     */
    task_id?: string;
    [property: string]: any;
}

/**
 * 任务类型
 */
export enum Action {
    AudioGeneration = "AUDIO_GENERATION",
    ImageGeneration = "IMAGE_GENERATION",
    The3DGeneration = "3D_GENERATION",
    VideoGeneration = "VIDEO_GENERATION",
}

/**
 * 任务结果数据对象
 *
 * 异步Task响应Result
 */
export interface 异步Task响应Result {
    /**
     * 生成的音频ur数组
     */
    audio_urls?: string[];
    /**
     * 生成的文件url数组，如3D文件
     */
    file_urls?: string[];
    /**
     * 生成的图片ur数组
     */
    image_urls?: string[];
    /**
     * 进度百分比：0-100
     */
    progress: number;
    /**
     * 生成的文本内容或音频转录文本
     */
    text?: string;
    /**
     * 生成的视频ur数组
     */
    video_urls?: string[];
    [property: string]: any;
}

/**
 * 任务状态，详见任务状态说明
 */
export enum Status {
    Cancelled = "CANCELLED",
    Completed = "COMPLETED",
    Failed = "FAILED",
    InProgress = "IN_PROGRESS",
    Submitted = "SUBMITTED",
    Submitting = "SUBMITTING",
}
```