"""完整工作流测试 - 测试所有6个步骤的串联"""
import asyncio
from core.agents.workflow_v2 import VideoCreationWorkflowV2


async def test_complete_workflow():
    """测试完整的6步工作流"""
    workflow = VideoCreationWorkflowV2()

    # 创建会话
    session_id = workflow.create_session()
    print(f'✓ 创建会话: {session_id[:8]}...\n')

    # 步骤1: 提交脚本和参数
    print('步骤 1: 提交脚本和参数')
    video_params = {
        'resolution': '1080p',
        'aspect_ratio': '16:9',
        'language': 'zh-CN',
        'style': 'cinematic',
        'perspective': 'third_person'
    }
    result = workflow.step_submit(
        session_id,
        '一个小女孩在森林里发现了一只受伤的小鹿，她决定帮助它。她温柔地包扎了小鹿的伤口，最终小鹿康复并回到了森林。',
        video_params
    )
    assert result['success'], f"步骤1失败: {result.get('error')}"
    print(f'✓ 步骤1完成\n')

    # 步骤2: 优化脚本
    print('步骤 2: 优化脚本')
    result = await workflow.step_optimize_script(session_id)
    assert result['success'], f"步骤2失败: {result.get('error')}"
    print(f'✓ 步骤2完成')
    print(f'  优化后脚本长度: {len(result["data"]["optimized_script"])} 字符\n')

    # 步骤3: 生成素材图
    print('步骤 3: 生成素材图')
    result = await workflow.step_generate_material_images(session_id)
    assert result['success'], f"步骤3失败: {result.get('error')}"
    print(f'✓ 步骤3完成')
    print(f'  生成素材图: {result["data"]["image_count"]} 张\n')

    # 步骤4: 生成分片脚本
    print('步骤 4: 生成分片脚本')
    result = await workflow.step_generate_segment_scripts(session_id)
    assert result['success'], f"步骤4失败: {result.get('error')}"
    print(f'✓ 步骤4完成')
    print(f'  生成分片: {result["data"]["segment_count"]} 个\n')

    # 步骤5: 生成首尾帧
    print('步骤 5: 生成首尾帧')
    result = await workflow.step_generate_segment_frames(session_id)
    assert result['success'], f"步骤5失败: {result.get('error')}"
    print(f'✓ 步骤5完成')
    data = result['data']
    print(f'  生成帧: {data["generated_count"]} 张, 复用: {data["reused_count"]} 张\n')

    # 步骤6: 生成视频
    print('步骤 6: 生成视频')
    result = await workflow.step_generate_videos(session_id)
    assert result['success'], f"步骤6失败: {result.get('error')}"
    print(f'✓ 步骤6完成')
    print(f'  生成视频: {result["data"]["success_count"]}/{result["data"]["video_count"]} 个\n')

    # 检查最终状态
    status = workflow.get_session_status(session_id)
    completed_steps = status.get('completed_steps', [])

    print('='*60)
    print('✅ 完整工作流测试成功！')
    print(f'已完成步骤 ({len(completed_steps)}/6):')
    for step in completed_steps:
        print(f'  - {step}')
    print('='*60)


if __name__ == '__main__':
    asyncio.run(test_complete_workflow())
