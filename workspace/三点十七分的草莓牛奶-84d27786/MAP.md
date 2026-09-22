---
updated_at: '2026-09-21T19:45:13.358182'
---

# 工作区地图：三点十七分的草莓牛奶

> 本文件由系统自动维护，是本剧本全部创作产物的目录地图与检索指引。

## 目录结构

- `MAP.md` — 本地图
- `00-ideation/story-logic.md` — 故事逻辑（构思收敛的故事设定全集）
- `01-outline/outline.md` — 全剧大纲（markdown 思维导图，根标题即剧名）
- `02-episodes/` — 分集设计（3 集）：
  - `ep_01-没人来买的那盒牛奶.md`
  - `ep_02-他住的那条街.md`
  - `ep_03-保质期.md`
- `03-entities/` — 实体卡（18 个）：
  - `chr_001-林夏.md`（人物）
  - `chr_002-陈伯.md`（人物）
  - `chr_003-林秋.md`（人物）
  - `chr_004-陈念.md`（人物）
  - `chr_005-大刘.md`（人物）
  - `chr_006-张婶.md`（人物）
  - `scn_001-便利店.md`（场景）
  - `scn_002-旧街区.md`（场景）
  - `scn_003-医院.md`（场景）
  - `scn_004-林夏的出租屋.md`（场景）
  - `scn_005-事故路口.md`（场景）
  - `clu_001-草莓牛奶.md`（线索）
  - `clu_002-监控录像.md`（线索）
  - `clu_003-配送记录.md`（线索）
  - `clu_004-女孩照片.md`（线索）
  - `fs_001-3点17分之谜.md`（伏笔）
  - `fs_002-不睡觉的理由.md`（伏笔）
  - `fs_003-路口的纪念花.md`（伏笔）
- `04-storyboards/` — 视频工作流分镜（按分集/视频会话组织）：
  - `ep_01/vs-7306c2a0/`（storyboard.md 导图 + seg_NN 分镜文件）
  - `ep_02/vs-9b105f08/`（storyboard.md 导图 + seg_NN 分镜文件）
  - `ep_03/vs-15f29c76/`（storyboard.md 导图 + seg_NN 分镜文件）

## 检索建议

- 全剧脉络与跨集伏笔：Read `01-outline/outline.md`
- 查人物/场景设定：Glob `03-entities/*.md`，或按名字 Grep
- 追某个伏笔的跨集动作（如 `fs_001`）：Grep 该 ID，命中各分集 frontmatter 的 foreshadow_refs 即埋设/回收位置
- 读某集结尾承接：Read 对应 `02-episodes/ep_NN-*.md` 的「结尾摘要」小节
- 分镜大纲与单镜提示词：Read `04-storyboards/{集}/vs-{会话}/` 下的 storyboard.md 与 seg_NN 文件

## 边界规则（Agent 必须遵守）

- 只能在本目录（`三点十七分的草莓牛奶-84d27786/`）内使用 Read/Grep/Glob，禁止读取工作区之外的任何路径
- 所有产物由系统统一写入；你只具备读权限，生成结果按任务要求返回