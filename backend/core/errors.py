"""核心业务异常基类

各工作流业务异常（ScriptWorkflowError / StoryboardError）继承本类，
main.py 只需注册本基类的全局异常 handler（message + status_code 协议）。
"""


class WorkflowError(Exception):
    """工作流业务错误（返回给前端 detail；status_code 供全局异常 handler 使用）"""

    def __init__(self, message: str, status_code: int = 400, reason: str = ""):
        """reason 为结构化原因（如 cancelled=用户主动取消），供上层透传给前端区分语义"""
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
