# 🔧 审核问题修复清单

## 🚨 Critical - 必须立即修复

### C1: API 响应暴露敏感信息
```bash
# 验证问题存在
grep -n "contact_phone\|contact_name" app/api/routes.py | grep -v "#"

# 修复
sed -i 's/contact_name":p.get("contact_name",""),//g' app/api/routes.py
sed -i 's/contact_phone":p.get("contact_phone",""),//g' app/api/routes.py
```

### C2: Session 内存存储
```bash
# 添加 Redis 依赖到 requirements.txt
echo "redis>=5.0.0" >> requirements.txt

# 创建 app/utils/redis_session.py
cat > app/utils/redis_session.py << 'PYEOF'
"""Redis Session 存储"""
import redis, json, secrets, os
from typing import Optional

class RedisSession:
    def __init__(self):
        self.redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        self.prefix = "session:"
        self.expiry = 7 * 24 * 3600
    
    def create(self, user_id: str, role: str) -> str:
        token = secrets.token_urlsafe(32)
        self.redis.setex(f"{self.prefix}{token}", self.expiry, json.dumps({"user_id": user_id, "role": role}))
        return token
    
    def get(self, token: str) -> Optional[dict]:
        data = self.redis.get(f"{self.prefix}{token}")
        return json.loads(data) if data else None
    
    def delete(self, token: str):
        self.redis.delete(f"{self.prefix}{token}")
PYEOF
```

### C3: CORS 中间件
```python
# 在 web_server.py 添加
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:9000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)
```

### C4: Webhook Key 默认值
```bash
# 在 routes_n8n.py 开头添加验证
import os
if not os.getenv("N8N_WEBHOOK_KEY"):
    raise RuntimeError("N8N_WEBHOOK_KEY environment variable must be set")
```

---

## 🟠 High - 近期必须解决

### H1: 测试覆盖
```bash
mkdir -p tests/test_api tests/test_db
touch tests/__init__.py tests/test_api/__init__.py tests/test_db/__init__.py

# conftest.py
cat > tests/conftest.py << 'PYEOF'
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture
def test_db():
    from app.database import Database
    db = Database(":memory:")
    yield db
    db.close()
PYEOF

# 示例测试
cat > tests/test_api/test_users.py << 'PYEOF'
import pytest

def test_create_user(test_db):
    user_id = test_db.create_user({
        "username": "test",
        "password_hash": "hash",
        "password_salt": "salt"
    })
    assert user_id is not None
    assert test_db.get_user_by_username("test") is not None
PYEOF
```

### H2: 移除硬编码管理员 ID
```python
# 修改 permissions.py 的 is_admin() 函数
def is_admin(self, user_id: str) -> bool:
    from app.database import get_db
    db = get_db()
    user = db.get_user_by_id(user_id)
    return user and user.get("role") == "admin"
```

### H3: API 权限装饰器
```python
# 在 routes.py 导入
from app.core.permissions import require_permission, Permission

# 为敏感 API 添加装饰器
@router.post("/api/favorites")
@require_permission(Permission.FAVORITES_ADD)
async def add_favorite(project: dict = Body(...)):
    ...
```

### H4: 移除 print 语句
```bash
# 查找所有 print
grep -rn "print(" app/ --include="*.py" | grep -v test

# 全部替换为 logger
find app -name "*.py" -exec sed -i 's/print(/logger.info(/g; s/logger\.info(\(.*\))/logger.info(\1)/g' {} \;
```

---

## ✅ 完成后验证

```bash
# 1. 检查无 print
grep -r "print(" app/ --include="*.py" | grep -v test

# 2. 检查 API 响应无敏感字段
curl -s http://localhost:9000/api/projects | grep -i "phone\|contact"

# 3. 检查 Redis 依赖
grep "redis" requirements.txt

# 4. 运行测试
python -m pytest tests/ -v
```
