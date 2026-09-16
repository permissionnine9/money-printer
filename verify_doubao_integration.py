#!/usr/bin/env python3
"""验证 doubao-seedance 服务集成"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

def test_import():
    """测试导入"""
    print("1. 测试模块导入...")
    try:
        from backend.core.services import VideoServiceDoubao, get_video_service
        from backend.core.config import VIDEO_SERVICE_TYPE
        print(f"   ✅ 导入成功，当前视频服务类型: {VIDEO_SERVICE_TYPE}")
        return True
    except Exception as e:
        print(f"   ❌ 导入失败: {e}")
        return False

def test_service_selection():
    """测试服务选择"""
    print("\n2. 测试服务选择...")
    try:
        from backend.core.services import get_video_service, VideoServiceDoubao

        # 测试 doubao 服务
        os.environ["VIDEO_SERVICE_TYPE"] = "doubao"
        service = get_video_service()
        print(f"   ✅ 获取服务类型: {type(service).__name__}")

        # 验证是 doubao 服务
        if isinstance(service, VideoServiceDoubao):
            print("   ✅ 正确选择了 doubao-seedance 服务")
            return True
        else:
            print(f"   ❌ 错误的服务类型: {type(service)}")
            return False
    except Exception as e:
        print(f"   ❌ 服务选择失败: {e}")
        return False

def test_config():
    """测试配置"""
    print("\n3. 测试配置...")
    try:
        from backend.core.config import SHENGSUANYUN_VIDEO_MODEL_DOUBAO
        print(f"   ✅ 豆包模型配置: {SHENGSUANYUN_VIDEO_MODEL_DOUBAO}")
        return True
    except Exception as e:
        print(f"   ❌ 配置测试失败: {e}")
        return False

def test_model_params():
    """测试模型参数转换"""
    print("\n4. 测试模型参数转换...")
    try:
        from backend.core.services.video_service_doubao import VideoServiceDoubao

        service = VideoServiceDoubao()

        # 测试分辨率转换
        assert service._get_resolution("1080p") == "1080p"
        assert service._get_resolution("4K") == "4k"
        assert service._get_resolution("720p") == "720p"
        print("   ✅ 分辨率转换正确")

        # 测试时长转换
        assert service._get_duration(5.0) == 5
        assert service._get_duration(8.0) == 10
        assert service._get_duration(12.0) == 10
        print("   ✅ 时长转换正确")

        # 测试宽高比转换
        assert service._get_ratio("16:9") == "16:9"
        assert service._get_ratio("9:16") == "9:16"
        assert service._get_ratio("1:1") == "1:1"
        print("   ✅ 宽高比转换正确")

        return True
    except Exception as e:
        print(f"   ❌ 参数转换测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=== 验证 doubao-seedance 服务集成 ===\n")

    # 设置环境变量为 doubao
    os.environ["VIDEO_SERVICE_TYPE"] = "doubao"

    tests = [
        test_import,
        test_service_selection,
        test_config,
        test_model_params
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1

    print(f"\n=== 测试结果 ===")
    print(f"通过: {passed}/{total}")

    if passed == total:
        print("🎉 所有测试通过！doubao-seedance 服务已正确集成")
        return 0
    else:
        print("❌ 部分测试失败，请检查配置")
        return 1

if __name__ == "__main__":
    exit(main())