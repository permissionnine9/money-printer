"""
测试 FastAPI 后端 API
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_health():
    """测试健康检查"""
    response = requests.get(f"{BASE_URL}/health")
    print(f"Health Check: {response.json()}")
    assert response.status_code == 200

def test_create_session():
    """测试创建会话"""
    response = requests.post(f"{BASE_URL}/api/v1/sessions")
    print(f"Create Session: {response.json()}")
    assert response.status_code == 201
    return response.json()["session_id"]

def test_get_session(session_id):
    """测试获取会话"""
    response = requests.get(f"{BASE_URL}/api/v1/sessions/{session_id}")
    print(f"Get Session: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    assert response.status_code == 200

def test_list_sessions():
    """测试获取会话列表"""
    response = requests.get(f"{BASE_URL}/api/v1/sessions")
    print(f"List Sessions: {response.json()}")
    assert response.status_code == 200

if __name__ == "__main__":
    print("开始测试 API...")
    print("-" * 50)
    
    # 测试健康检查
    test_health()
    print()
    
    # 测试创建会话
    session_id = test_create_session()
    print()
    
    # 测试获取会话
    test_get_session(session_id)
    print()
    
    # 测试会话列表
    test_list_sessions()
    print()
    
    print("-" * 50)
    print("所有测试通过！")
