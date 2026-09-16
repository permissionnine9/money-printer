# 工作流串联问题修复总结

## 问题描述

用户反馈重构后的工作流"完全串不起来"，经过测试发现虽然基础串联逻辑正常，但图片生成服务存在严重问题，导致：
- 日志不停输出"未知状态: completed，继续等待..."
- 轮询任务永远无法正常结束
- 步骤5（生成首尾帧）因此失败

## 根本原因

### 1. API 返回格式理解错误

盛算云 API 的返回格式是：
```json
{
  "code": "success",  // API 调用是否成功
  "data": {
    "status": "COMPLETED",  // 实际的任务状态
    "request_id": "...",
    ...
  }
}
```

但代码错误地使用 `result.get("code")` 来判断任务状态，应该使用 `result["data"]["status"]`。

### 2. 轮询逻辑不完整

轮询方法中只检查了 `status == "pending"` 和 `status == "failed"`，没有处理 `status == "completed"` 的情况。当任务完成但图片URL提取失败时（`success=False, status="completed"`），轮询逻辑将其视为"未知状态"并继续等待，导致死循环。

## 修复方案

### 修复文件

`src/services/image_service.py`

### 修复内容

#### 1. 修复 `query_task_result` 方法 (第126-182行)

**修改前**：
```python
status = result.get("code", "").lower()  # 错误：读取 API 调用状态而非任务状态
```

**修改后**：
```python
api_code = result.get("code", "").lower()
data = result.get("data", {})
task_status = data.get("status", "").upper()  # 正确：读取任务状态

# 分别处理 API 调用状态和任务状态
if task_status == "COMPLETED":
    # 任务完成...
elif task_status in ("PENDING", "SUBMITTING", ...):
    # 任务处理中...
```

#### 2. 修复所有轮询方法（4处）

在以下方法中添加对 `status == "completed"` 的处理：
- `_generate_image` (第290-310行)
- `poll_i2i_task` (第410-432行)
- `generate_material_images_with_reference` 内部循环 (第554-576行)
- `edit_material_image` 内部循环 (第933-955行)

**修改前**：
```python
if status == "pending":
    logger.info(f"任务处理中...")
    continue

logger.warning(f"未知状态: {status}，继续等待...")  # 死循环！
```

**修改后**：
```python
if status == "completed":
    # 已完成但提取图片失败，直接返回错误
    logger.error(f"任务已完成但处理失败: {query_result.get('error')}")
    return {"success": False, "error": query_result.get("error", "图片URL提取失败")}

if status == "pending":
    logger.info(f"任务处理中...")
    continue

# 对未知状态返回错误而不是继续等待
logger.warning(f"未知状态: {status}，返回错误")
return {"success": False, "error": f"未知状态: {status}"}
```

## 验证结果

修复后测试：
- ✅ 步骤1-4 全部成功
- ✅ 不再出现"未知状态: completed，继续等待..."日志
- ✅ 轮询逻辑能正确终止
- ⚠️ 步骤5部分失败（13张图片），但原因是 API 端问题（URL 无法访问），而非代码逻辑问题

## 测试代码

创建了完整工作流测试：`test_workflow_complete.py`

```bash
uv run python test_workflow_complete.py
```

## 总结

此次修复解决了核心的轮询死循环问题，使工作流能够正常串联。剩余的图片生成失败问题是 API 端的 URL 访问问题，属于外部依赖问题，不影响工作流的串联逻辑。

**关键教训**：
1. 仔细理解第三方 API 的返回格式
2. 轮询逻辑必须处理所有可能的状态，包括成功但失败的情况
3. 对未知状态应该快速失败而不是继续等待
