/**
 * Step5Frames 组件的类型定义
 */

export interface MaterialImage {
  image_path: string
  [key: string]: unknown
}

export interface FrameData {
  segment_index: number
  first_status?: string
  last_status?: string
  first_image_path?: string
  last_image_path?: string
  first_prompt?: string
  last_prompt?: string
  [key: string]: unknown
}

export interface SegmentInfo {
  content?: string
  action?: string
  camera_movement?: string
  composition?: string
  atmosphere?: string
  duration?: number
  first_frame_mode?: string
  [key: string]: unknown
}

export interface EditFrameInfo {
  frame: unknown
  segment: SegmentInfo | undefined
  originalPrompt: string
  currentImagePath: string
}

export interface SegmentFormData {
  content: string
  duration: number
  action?: string
  camera_movement?: string
  composition?: string
  atmosphere?: string
}

export interface EditModalState {
  visible: boolean
  segmentIndex: number
  frameType: 'first' | 'last'
  activeTab: string
  selectedSourceSegment: number | null
  selectedSourceFrameType: 'first' | 'last' | null
  selectedMaterialIndices: number[]
  regenerateMode: 'material' | 'current_frame'
  uploadedMaterialPaths: string[]
}

export interface AvailableFrame {
  segmentIndex: number
  frameType: 'first' | 'last'
  imagePath: string
  label: string
}
