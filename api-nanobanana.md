## nano banana 图生图请求

curl --location --request POST 'https://router.shengsuanyun.com/api/v1/tasks/generations' \
--header 'Authorization: Bearer <token>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "google/gemini-3-pro-image-preview",
    "prompt": "第二张图中的女孩，带着第三张图中的眼镜，抱着第一张图中的小猫",
    "images": [
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABoAAAAOgCAIAAACSr...",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABTAAAAUwCAIAAAD7D...",
        "data:image/jpg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST...",
    ]
}'


## 请求参数说明
/**
 * 常规请求格式
 *
 * Gemini 图片生成请求体-常规
 *
 * 对话式构建请求体
 *
 * Gemini 图片生成请求体-Messages
 */
export interface ApifoxModel {
    /**
     * 生成图片比例，正式版模型支持
     */
    aspect_ratio?: AspectRatio;
    /**
     * 用于参考的图片Url数组，支持base64编码
     */
    images?: string[];
    /**
     * 模型名称
     */
    model: Model;
    /**
     * 正向提示词，描述生成图像中期望包含的元素和视觉特点
     */
    prompt?: string;
    /**
     * ["IMAGE"] 或 ["TEXT", "IMAGE"] （preview版本模型只支持 ["TEXT", "IMAGE"] ）
     *
     * ["IMAGE"] 或 ["TEXT", "IMAGE"] （preview版模型仅支持 ["TEXT", "IMAGE"]）
     */
    response_modalities?: string[];
    /**
     * gemini-3-pro-image-preview独有参数
     */
    size?: Size;
    /**
     * 以多轮对话构建请求体
     */
    messages?: Message[];
    /**
     * 系统提示词
     */
    system?: string;
    [property: string]: any;
}

/**
 * 生成图片比例，正式版模型支持
 */
export enum AspectRatio {
    The11 = "1:1",
    The169 = "16:9",
    The219 = "21:9",
    The23 = "2:3",
    The32 = "3:2",
    The34 = "3:4",
    The43 = "4:3",
    The45 = "4:5",
    The54 = "5:4",
    The916 = "9:16",
}

export interface Message {
    /**
     * 图片Url
     */
    image?: string;
    /**
     * 文字
     */
    text?: string;
    [property: string]: any;
}

/**
 * 模型名称
 */
export enum Model {
    GoogleGemini25FlashImage = "google/gemini-2.5-flash-image",
    GoogleGemini3ProImagePreview = "google/gemini-3-pro-image-preview",
}

/**
 * gemini-3-pro-image-preview独有参数
 */
export enum Size {
    The1K = "1K",
    The2K = "2K",
    The4K = "4K",
}

## response参数说明

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