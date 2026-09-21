---
name: agent-read-image-buffer
摘要: Agent（READ_ONLY_TOOLS 含 Read）Read 2K/4K 原图时 tool_result 整图 base64 回显，超 SDK stream-json 默认 1MB 缓冲报错中断；wrapper 传 max_buffer_size=16MB 修复。
tags: [claude-agent-sdk, stream-json, buffer, 图片, Read]
---

# Agent Read 图片撑爆 stream-json 缓冲

**最后更新:** 2026-09-21

## 问题

agent（READ_ONLY_TOOLS 含 Read）在工作区 Read 2K/4K 原图时，tool_result 以整图 base64 回显，SDK 读 CLI 子进程 stdout 的 stream-json 单条消息超过默认 1MB 缓冲即报错：

```
JSON message exceeded maximum buffer size of 1048576 bytes
```

run 中断，生成任务失败。

## 根因

ClaudeSDKClient 默认 `max_buffer_size=1MB`；图片 base64 膨胀约 1.33 倍，2K/4K 原图极易超限。

## 解决

`backend/core/agent_sdk/wrapper.py`：

- 新增模块常量 `MAX_STREAM_BUFFER_SIZE = 16 * 1024 * 1024`；
- 构造 `ClaudeAgentOptions` 时传 `max_buffer_size=MAX_STREAM_BUFFER_SIZE`。

## 避免

- 让 agent 读大图前先压缩（复用 `IMAGE_COMPRESS_MAX_SIZE=1920` 的压缩链路），从源头控制消息体大小；
- 新接入 claude-agent-sdk（或任何子进程 stream-json 协议）时，评估子进程单条消息体上限并显式配置 buffer 上限。
