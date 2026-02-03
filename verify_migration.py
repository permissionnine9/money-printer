#!/usr/bin/env python3
"""验证 src → core 迁移的脚本"""

import sys
import os

def check_imports():
    """检查是否还有 from src. 导入"""
    print("🔍 检查导入语句...")
    errors = []
    
    # 检查 backend
    for root, dirs, files in os.walk("backend"):
        # 跳过 __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                with open(filepath, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if "from src." in line or "import src." in line:
                            errors.append(f"{filepath}:{i}: {line.strip()}")
    
    # 检查 core
    for root, dirs, files in os.walk("core"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                with open(filepath, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if "from src." in line or "import src." in line:
                            errors.append(f"{filepath}:{i}: {line.strip()}")
    
    if errors:
        print("❌ 发现未更新的导入语句:")
        for error in errors:
            print(f"   {error}")
        return False
    else:
        print("✅ 所有导入语句已正确更新为 'from core.'")
        return True

def check_directories():
    """检查目录结构"""
    print("\n🔍 检查目录结构...")
    
    if os.path.exists("src") and not os.path.islink("src"):
        print("❌ 发现 src 目录（应该已重命名为 core）")
        return False
    
    if not os.path.exists("core"):
        print("❌ core 目录不存在")
        return False
    
    if not os.path.exists("src.backup"):
        print("⚠️  警告：未找到 src.backup 备份目录")
    else:
        print("✅ 找到备份目录 src.backup")
    
    # 检查 core 目录结构
    required_dirs = ["agents", "models", "services", "persistence", "utils"]
    missing = []
    for d in required_dirs:
        if not os.path.exists(f"core/{d}"):
            missing.append(d)
    
    if missing:
        print(f"❌ core 目录缺少子目录: {', '.join(missing)}")
        return False
    
    print("✅ core 目录结构完整")
    return True

def check_core_imports():
    """检查 core 模块是否可以导入"""
    print("\n🔍 检查 core 模块导入...")
    
    try:
        # 测试导入核心模块
        from core.models import video_models
        print("✅ core.models.video_models 导入成功")
        
        from core.config import SHENGSUANYUN_API_KEY
        print("✅ core.config 导入成功")
        
        # 测试导入 SessionManager
        from core.persistence.session_manager import SessionManager
        print("✅ core.persistence.session_manager.SessionManager 导入成功")
        
        # 测试导入 workflow
        from core.agents.workflow_v2 import VideoCreationWorkflowV2
        print("✅ core.agents.workflow_v2.VideoCreationWorkflowV2 导入成功")
        
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False

def main():
    print("=" * 60)
    print("  src → core 迁移验证")
    print("=" * 60)
    print()
    
    checks = [
        check_directories(),
        check_imports(),
        check_core_imports(),
    ]
    
    print("\n" + "=" * 60)
    if all(checks):
        print("✅ 所有检查通过！迁移成功！")
        print("=" * 60)
        print("\n后续步骤:")
        print("1. 启动后端测试: cd backend && uv run uvicorn backend.main:app --reload")
        print("2. 启动前端测试: cd frontend && npm run dev")
        print("3. 如果测试通过，删除备份: rm -rf src.backup")
        return 0
    else:
        print("❌ 部分检查失败，请修复后重试")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
