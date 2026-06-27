"""
Redis URL 解析工具 — 调度器和采集器共用

用法:
    from app.utils.redis_url import parse_redis_url
    params = parse_redis_url(REDIS_URL)
    redis.Redis(host=..., port=..., db=..., password=...)
"""

import re


def parse_redis_url(url: str) -> dict:
    """解析 redis:// URL 为 redis-py 连接参数"""
    m = re.match(r"redis://(?::([^@]+)@)?([^:]+):(\d+)(?:/(\d+))?", url)
    if not m:
        return {"host": "localhost", "port": 6379, "db": 0, "password": None}
    password, host, port, db = m.groups()
    return {
        "host": host,
        "port": int(port),
        "db": int(db) if db else 0,
        "password": password,
    }
