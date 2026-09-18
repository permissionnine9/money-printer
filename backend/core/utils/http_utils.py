"""HTTP 公共工具：统一的文件下载（stream 分块写盘，避免大文件一次性读入内存）"""
from pathlib import Path

import httpx


async def download_to_file(url: str, dest: Path, timeout: float = 150.0) -> str:
    """下载 URL 内容到本地文件（stream 分块写盘）

    Returns:
        本地文件路径字符串
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
    return str(dest)
