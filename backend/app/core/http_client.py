"""
全局异步 HTTP 客户端池
提供统一的 httpx AsyncClient 配置，用于所有外部 API 调用
"""
import asyncio
from typing import Optional
import httpx
from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("http_client")


class HTTPClientPool:
    """全局 HTTP 客户端池，支持连接复用和并发控制"""
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
    
    async def get_client(self) -> httpx.AsyncClient:
        """获取全局异步 HTTP 客户端（懒加载）"""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    # 配置连接池和超时
                    limits = httpx.Limits(
                        max_connections=100,  # 最大连接数
                        max_keepalive_connections=20,  # 保持活动的连接数
                        keepalive_expiry=30.0,  # 连接保持时间（秒）
                    )
                    
                    timeout = httpx.Timeout(
                        connect=10.0,  # 连接超时
                        read=60.0,  # 读取超时
                        write=30.0,  # 写入超时
                        pool=5.0,  # 连接池获取超时
                    )
                    
                    self._client = httpx.AsyncClient(
                        limits=limits,
                        timeout=timeout,
                        follow_redirects=True,
                        http2=True,  # 启用 HTTP/2
                    )
                    logger.info("HTTP client pool initialized with max_connections=100")
        
        return self._client
    
    async def close(self):
        """关闭客户端连接池"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("HTTP client pool closed")
    
    async def request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
        **kwargs
    ) -> httpx.Response:
        """
        发送 HTTP 请求，支持自动重试
        
        Args:
            method: HTTP 方法 (GET, POST, etc.)
            url: 请求 URL
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒）
            backoff_factor: 退避因子（每次重试延迟乘以此因子）
            **kwargs: httpx.request 的其他参数
        
        Returns:
            HTTP 响应
        
        Raises:
            httpx.HTTPError: 请求失败
        """
        client = await self.get_client()
        last_exception = None
        current_delay = retry_delay
        
        for attempt in range(max_retries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < max_retries:
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor
                else:
                    logger.error(f"Request failed after {max_retries + 1} attempts: {e}")
            
            except httpx.HTTPStatusError as e:
                # 对于 5xx 错误重试，4xx 错误直接抛出
                if e.response.status_code >= 500 and attempt < max_retries:
                    last_exception = e
                    logger.warning(
                        f"Server error {e.response.status_code} (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor
                else:
                    raise
        
        # 所有重试都失败了
        if last_exception:
            raise last_exception
        
        # 不应该到达这里
        raise RuntimeError("Unexpected error in request_with_retry")
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET 请求（带重试）"""
        return await self.request_with_retry("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST 请求（带重试）"""
        return await self.request_with_retry("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT 请求（带重试）"""
        return await self.request_with_retry("PUT", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE 请求（带重试）"""
        return await self.request_with_retry("DELETE", url, **kwargs)


# 全局单例
_http_client_pool: Optional[HTTPClientPool] = None


def get_http_client_pool() -> HTTPClientPool:
    """获取全局 HTTP 客户端池实例"""
    global _http_client_pool
    if _http_client_pool is None:
        _http_client_pool = HTTPClientPool()
    return _http_client_pool


async def close_http_client_pool():
    """关闭全局 HTTP 客户端池"""
    global _http_client_pool
    if _http_client_pool is not None:
        await _http_client_pool.close()
        _http_client_pool = None


__all__ = [
    "HTTPClientPool",
    "get_http_client_pool",
    "close_http_client_pool",
]

