# tender-scraper 项目审核报告

> 审核时间: 2026-04-04
> 审核级别: 严厉批判
> 综合评分: 4/10

---

## 🔴 Critical - 必须立即修复

### C1: API 响应暴露敏感信息
**文件**: `app/api/routes.py:335`
**问题**: contact_phone 和 contact_name 直接暴露在 API 响应中

```python
# 当前代码 (错误)
std=[{...,"contact_name":p.get("contact_name",""),
     "contact_phone":p.get("contact_phone","")}for p in projects]
```

**修复方案**:
1. 使用 `app/utils/sensitive.py` 中的 `sanitize_response()` 函数
2. 修改为:
```python
from app.utils.sensitive import sanitize_response
std=[sanitize_response(p) for p in projects]
```

**验收标准**: API 响应中 contact_phone 和 contact_name 必须脱敏或移除

---

### C2: Session 内存存储无法水平扩展
**文件**: `app/api/routes_users.py`
**问题**: `_sessions = {}` 重启服务全部丢失，多实例无法共享

**修复方案**: 使用 Redis 存储 Session
1. 添加依赖: `redis>=5.0.0`
2. 创建 `app/utils/redis_session.py`:
```python
import redis
import json
import os

class RedisSession:
    def __init__(self):
        self.redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        self.prefix = "session:"
        self.expiry = 7 * 24 * 3600  # 7天
    
    def create(self, user_id: str, role: str) -> str:
        import secrets
        token = secrets.token_urlsafe(32)
        data = {"user_id": user_id, "role": role}
        self.redis.setex(f"{self.prefix}{token}", self.expiry, json.dumps(data))
        return token
    
    def get(self, token: str) -> dict:
        data = self.redis.get(f"{self.prefix}{token}")
        return json.loads(data) if data else None
    
    def delete(self, token: str):
        self.redis.delete(f"{self.prefix}{token}")
```

3. 替换 `routes_users.py` 中的 session 相关函数

**验收标准**: 服务重启后 Session 保持有效

---

### C3: 缺少 CORS 中间件
**文件**: `web_server.py`
**问题**: 无法控制跨域访问

**修复方案**:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

**验收标准**: 只允许指定域名访问 API

---

### C4: Webhook Key 弱默认值
**文件**: `app/api/routes_n8n.py:37`
**问题**: 硬编码 `n8n_secret_key` 默认值

**修复方案**:
```python
# 禁止使用默认密钥
expected_key = os.getenv("N8N_WEBHOOK_KEY")
if not expected_key:
    raise ValueError("N8N_WEBHOOK_KEY 环境变量必须设置")
```

**验收标准**: 未设置环境变量时服务启动失败

---

## 🟠 High - 近期必须解决

### H1: 零测试覆盖
**问题**: 无任何测试文件

**修复方案**: 创建测试目录和基础测试
```
tests/
├── __init__.py
├── conftest.py
├── test_api/
│   ├── __init__.py
│   ├── test_routes.py
│   └── test_users.py
└── test_db/
    ├── __init__.py
    └── test_database.py
```

**conftest.py**:
```python
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture
def test_db():
    from app.database import Database
    db = Database(":memory:")
    yield db
    db.close()
```

**验收标准**: 至少 10 个测试用例，覆盖核心功能

---

### H2: 管理员 ID 硬编码
**文件**: `config/admin_users.json`, `app/core/permissions.py`

**修复方案**:
1. 将管理员 ID 存入数据库 users 表
2. admin_users.json 仅作为备份恢复使用
3. `is_admin()` 函数改为查询数据库:
```python
def is_admin(self, user_id: str) -> bool:
    user = self.get_user(user_id)
    return user and user.role == "admin"
```

**验收标准**: 管理员身份由数据库控制，不依赖配置文件

---

### H3: API 路由缺少权限装饰器
**文件**: `app/api/routes.py`
**问题**: 所有 60+ 个路由无权限控制

**修复方案**: 为敏感 API 添加权限装饰器
```python
from app.core.permissions import require_permission, Permission

@router.post("/api/favorites")
@require_permission(Permission.FAVORITES_ADD)
async def add_favorite(...):
```

权限列表:
- `DATA_VIEW`, `DATA_EXPORT`, `DATA_DELETE`
- `FAVORITES_VIEW`, `FAVORITES_ADD`, `FAVORITES_REMOVE`, `FAVORITES_UPDATE`
- `SCRAPE_TRIGGER`, `SCRAPE_STOP`
- `SYSTEM_MANAGE_USERS`, `SYSTEM_VIEW_LOGS`

**验收标准**: 未登录用户无法访问需要认证的 API

---

### H4: 仍有 print 语句
**文件**: `app/core/concurrency_scheduler.py:373,377`

**修复方案**: 替换为 logger
```python
# 错误
print(f"{status} {r.task_id}: ...")

# 正确
logger.info(f"{status} {r.task_id}: ...")
```

**验收标准**: 全局搜索无 `print(` 语句

---

## 🟡 Medium - 短期应优化

### M1: 错误处理过宽
**问题**: 65 个 `except Exception as e:`

**修复方案**: 细分异常类型
```python
# 错误
except Exception as e:
    logger.error(f"...")

# 正确
except (IOError, OSError) as e:
    logger.error(f"IO error: {e}")
except TimeoutError as e:
    logger.error(f"Timeout: {e}")
except ValueError as e:
    logger.error(f"Validation error: {e}")
```

---

### M2: 函数缺少类型提示
**修复方案**: 为所有函数添加返回类型
```python
# 当前
def get_user(username: str):

# 正确
def get_user(username: str) -> Optional[dict]:
```

---

### M3: 缺少数据库迁移机制
**修复方案**: 引入 Alembic
```bash
pip install alembic
alembic init alembic
```

---

### M4: API 缺少 Swagger 注解
**修复方案**:
```python
@router.get("/projects",
    summary="获取项目列表",
    description="分页获取招标项目，支持筛选",
    response_model=List[Project],
    tags=["项目"]
)
async def get_projects(...):
```

---

## 📋 修复优先级清单

### 第1周 (Critical)
- [ ] C1: 修复 API 响应脱敏
- [ ] C4: 移除硬编码密钥默认值
- [ ] H4: 替换 print 为 logger

### 第2周 (Critical + High)
- [ ] C2: 实现 Redis Session
- [ ] C3: 添加 CORS 中间件
- [ ] H2: 数据库管理管理员身份

### 第3-4周 (High)
- [ ] H1: 编写基础测试用例
- [ ] H3: 添加 API 权限装饰器

### 长期 (Medium)
- [ ] M1-M4: 错误处理优化、类型提示、迁移机制、API 文档

---

## ✅ 验收检查清单

运行以下命令验证:

```bash
# 1. 无 print 语句
grep -r "print(" app/ --include="*.py" | grep -v test

# 2. API 响应脱敏
curl -s http://localhost:9000/api/projects | grep -i "phone\|contact"

# 3. Session 持久化
# 重启服务后检查登录状态是否保持

# 4. CORS 配置
curl -I -X OPTIONS http://localhost:9000/api/projects \
  -H "Origin: https://evil.com"

# 5. 权限控制
# 未登录访问 /api/favorites 应返回 401
```

---

## 📊 评分变化目标

| 维度 | 当前 | 目标 |
|------|------|------|
| 安全性 | 4/10 | 7/10 |
| 代码质量 | 5/10 | 7/10 |
| 测试覆盖 | 1/10 | 5/10 |
| 架构设计 | 6/10 | 7/10 |
| 文档 | 4/10 | 6/10 |
| **综合** | **4/10** | **6.5/10** |
