/**
 * OpenAI图像生成参数
 */
export interface ApifoxModel {
    /**
     * 背景透明度，仅gpt-image-1支持。可选：transparent、opaque、auto。transparent时需要使用png或webp格式。
     */
    background?: Background;
    /**
     * 传入单张图片base64 或者 公网可访问url
     */
    image?: string;
    /**
     * 传入多图片base64 或者 公网可访问url
     */
    images?: string[];
    /**
     * 传入单张mask 图片base64 或者 公网可访问url
     */
    mask?: string;
    /**
     * 模型名称
     */
    model: Model;
    /**
     * 内容审核级别，仅gpt-image-1支持。可选：low（较少限制）、auto。
     */
    moderation?: Moderation;
    /**
     * 生成图片的数量 1-10
     */
    n?: number;
    /**
     * 压缩级别（0-100%），仅gpt-image-1的webp或jpeg格式支持。
     */
    output_compression?: number;
    /**
     * 输出格式，仅gpt-image-1支持。可选：png、jpeg、webp。
     */
    output_format?: OutputFormat;
    /**
     * 正向提示词，描述生成图像中期望包含的元素和视觉特点
     */
    prompt: string;
    /**
     * 图像质量。gpt-image-1支持：auto、high、medium、low；dall-e-3支持：hd、standard；dall-e-2仅支持：standard。
     */
    quality?: Quality;
    /**
     * 生成图像的尺寸。对于 gpt-image-1，必须是 1024x1024、1536x1024（横版）、1024x1536（竖版）或 auto（默认值）中的一种；对于
     * dall-e-2，必须是 256x256、512x512 或 1024x1024 中的一种。
     */
    size?: Size;
    [property: string]: any;
}

/**
 * 背景透明度，仅gpt-image-1支持。可选：transparent、opaque、auto。transparent时需要使用png或webp格式。
 */
export enum Background {
    Auto = "auto",
    Opaque = "opaque",
    Transparent = "transparent",
}

/**
 * 模型名称
 */
export enum Model {
    OpenaigptImage1 = "openai/gpt-image-1",
    OpenaigptImage15 = "openai/gpt-image-1.5",
}

/**
 * 内容审核级别，仅gpt-image-1支持。可选：low（较少限制）、auto。
 */
export enum Moderation {
    Auto = "auto",
    Low = "low",
}

/**
 * 输出格式，仅gpt-image-1支持。可选：png、jpeg、webp。
 */
export enum OutputFormat {
    Jpeg = "jpeg",
    Png = "png",
    Webp = "webp",
}

/**
 * 图像质量。gpt-image-1支持：auto、high、medium、low；dall-e-3支持：hd、standard；dall-e-2仅支持：standard。
 */
export enum Quality {
    Auto = "auto",
    Hd = "hd",
    High = "high",
    Low = "low",
    Medium = "medium",
    Standard = "standard",
}

/**
 * 生成图像的尺寸。对于 gpt-image-1，必须是 1024x1024、1536x1024（横版）、1024x1536（竖版）或 auto（默认值）中的一种；对于
 * dall-e-2，必须是 256x256、512x512 或 1024x1024 中的一种。
 */
export enum Size {
    Auto = "auto",
    The1024X1024 = "1024x1024",
    The1024X1536 = "1024x1536",
    The1024X1792 = "1024x1792",
    The1536X1024 = "1536x1024",
    The1792X1024 = "1792x1024",
    The256X256 = "256x256",
    The512X512 = "512x512",
}