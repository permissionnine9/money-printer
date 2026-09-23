- 通常不需要前端交互验证 ，如果一定要验证，那么就用 ‘/ego-browser‘ skill完成
- 不能自己提交、不能自己暂存、不能自己操作 git记录等

## 导入到 ComfyUI技术方案
你点「导入到 ComfyUI」
     ↓ 后端照常上传素材 + 注入 timeline_data
     ↓ 新增：同时把注入后的【UI 版工作流】写到服务器
       user/default/workflows/money-printer/导入_{会话ID}.json

## 没有叫你操作comfyUI验证的时候，不要操作，但是读取是可以的

## 不要帮我乱加代码，要考虑项目的架构，我最讨厌垃圾代码。