import http.client
import json

conn = http.client.HTTPSConnection("router.shengsuanyun.com")
payload = json.dumps({
   "model": "bytedance/doubao-seedance-1.0-pro",
   "image": "https://example.com/start.jpg",
   "image_role": "first_frame",
   <!-- 如果有尾帧，则添加此项image_tail和image_tail_role -->
   "image_tail": "https://example.com/end.jpg",
   "image_tail_role": "last_frame",
   "prompt": "从起始状态平滑过渡到结束状态",
   <!-- 720p, 1080p, 2k, 4k -->
   "resolution": "720p",
   "ratio": "adaptive",
   <!-- 5s 或者10s -->
   "duration": 10,
   <!-- 16 或者24 -->
   "fps": 24
})
headers = {
   'Authorization': 'Bearer <token>',
   'Content-Type': 'application/json'
}
conn.request("POST", "/api/v1/tasks/generations", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))




/**
 * 豆包视频生成请求体
 */
export interface ApifoxModel {
    /**
     * 回调 URL（可选）
     */
    callback_url?: string;
    /**
     * 是否固定摄像头
     */
    camera_fixed?: boolean;
    /**
     * 视频时长（秒）
     */
    duration?: number;
    /**
     * 视频帧率
     */
    fps?: number;
    /**
     * 首帧图像，支持 URL 或 Base64 编码（格式：data:image/<格式>;base64,<编码>）
     */
    image?: string;
    /**
     * 参考图片数组，最多 4 张，不能与 image 同时使用
     */
    image_list?: ImageList[];
    /**
     * 首帧图像的角色
     */
    image_role?: ImageRole;
    /**
     * 尾帧图像，支持 URL 或 Base64 编码，仅在有 image 时可用
     */
    image_tail?: string;
    /**
     * 尾帧图像的角色
     */
    image_tail_role?: ImageTailRole;
    /**
     * 视频生成模型 ID
     */
    model: Model;
    /**
     * 文本提示词，支持中英文，可以在末尾添加 --参数 格式的文本命令
     */
    prompt: string;
    /**
     * 视频宽高比
     */
    ratio?: Ratio;
    /**
     * 视频分辨率
     */
    resolution?: Resolution;
    /**
     * 随机种子，-1 表示随机
     */
    seed?: number;
    /**
     * 是否添加水印
     */
    watermark?: boolean;
    [property: string]: any;
}

export interface ImageList {
    /**
     * 参考图片 URL 或 Base64 编码
     */
    image: string;
    /**
     * 图片角色
     */
    role?: Role;
    [property: string]: any;
}

/**
 * 图片角色
 */
export enum Role {
    ReferenceImage = "reference_image",
}

/**
 * 首帧图像的角色
 */
export enum ImageRole {
    FirstFrame = "first_frame",
}

/**
 * 尾帧图像的角色
 */
export enum ImageTailRole {
    LastFrame = "last_frame",
}

/**
 * 视频生成模型 ID
 */
export enum Model {
    BytedanceDoubaoSeedance10LiteI2V = "bytedance/doubao-seedance-1.0-lite-i2v",
    BytedanceDoubaoSeedance10LiteT2V = "bytedance/doubao-seedance-1.0-lite-t2v",
    BytedanceDoubaoSeedance10Pro = "bytedance/doubao-seedance-1.0-pro",
}

/**
 * 视频宽高比
 */
export enum Ratio {
    Adaptive = "adaptive",
    KeepRatio = "keep_ratio",
    The11 = "1:1",
    The169 = "16:9",
    The219 = "21:9",
    The34 = "3:4",
    The43 = "4:3",
    The916 = "9:16",
}

/**
 * 视频分辨率
 */
export enum Resolution {
    The1080P = "1080p",
    The480P = "480p",
    The720P = "720p",
}