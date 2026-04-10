# 🔒 安全审计报告 — tender-scraper

> **审计角色**: 安全工程师
> **审计日期**: 2026-04-07
> **审计范围**: ~/tender-scraper
> **综合评分**: **6.8/10** (较上次 7.5 略有降低——发现新问题)

---

## 一、输入验证

### ✅ 已实现
- `sanitize_input()` — 过滤 `<>"'` 字符
- `validate_url()`, `validate_email()`, `validate_username()` — 基础校验
- Pydantic schemas — API 请求模型验证
- SQL 参数化查询 — 58 处全部参数化，无 SQL 注入

### 🔴 发现问题

#### I-1: `sanitize_input` 过滤不完整 — XSS 风险 ⚠️

**文件**: `app/utils/security.py`

```python
text = re.sub(r"[<>\"']", "", text)
```

**问题**:
- 仅过滤了 4 种字符，未过滤 `\`, 反引号、空格、换行
- 攻击向量示例: `<img src=x onerror=alert(1)>`
- `onerror` 不包含在过滤列表中

**修复建议**:
```python
import html
text = html.escape(text)  # 全面转义 HTML 特殊字符
```

**严重程度**: 🟠 High | **可利用**: Yes (需审查前端是否渲染)

---

#### I-2: `/api/n8n/push-to-n8n` — SSRF 无验证 ⚠️

**文件**: `app/api/routes_n8n.py`

```python
@router.post("/push-to-n8n")
async def push_to_n8n(
    project_urls: List[str] = Body(...),
    n8n_url: str = Body(..., description="n8n webhook URL"),
):
```

**问题**:
- `n8n_url` 为用户可控的任意 URL
- 攻击者可利用内网服务: `http://169.254.169.254/latest/meta-data/` (云元数据)
- 攻击者可扫描内网端口和服务
- 无 URL 白名单、无 scheme 限制

**修复建议**:
```python
from urllib.parse import urlparse
ALLOWED_SCHEMES = {"https"}
ALLOWED_HOSTS = {"your-n8n-domain.com"}

def validate_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False
    if parsed.hostname not in ALLOWED_HOSTS:
        return False
    return True
```

**严重程度**: 🔴 Critical | **可利用**: Yes

---

#### I-3: `/api/db/backup/download` — 路径遍历 ⚠️

**文件**: `app/api/routes/database.py`

```python
@router.get("/backup/download")
def download_backup(path: str = Query(...)):
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(path, filename=p.name, media_type="application/octet-stream")
```

**问题**:
- 无路径规范化检查
- 攻击者可用 `path=../../.env` 下载敏感配置
- 攻击者可用 `path=/etc/passwd` 下载系统文件

**修复建议**:
```python
SAFE_DIR = Path(__file__).parent.parent.parent / "config" / "db_backups"
resolved = SAFE_DIR / path
if not resolved.resolve().is_relative_to(SAFE_DIR.resolve()):
    return JSONResponse({"error": "非法路径"}, status_code=400)
```

**严重程度**: 🔴 Critical | **可利用**: Yes

---

#### I-4: `/api/collect` — 任意命令执行风险 ⚠️

**文件**: `app/api/routes/notifications_settings.py`

```python
@router.post("/collect")
async def trigger_collection():
    ...
    from main import run_collection
    result = await run_collection()
```

**问题**:
- `/collect` 端点无认证保护
- 任何人可触发采集任务
- 无 rate limit

**修复建议**:
```python
@router.post("/collect")
@require_permission(Permission.SCRAPE_TRIGGER)
async def trigger_collection(...):
```

**严重程度**: 🟠 High | **可利用**: Yes (无认证)

---

#### I-5: `update_user` — 动态 SET 子句 SQL 注入 ⚠️

**文件**: `app/database/db.py`

```python
def update_user(self, user_id: str, updates: dict):
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [user_id]
    conn.execute(
        f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        values,
    )
```

**问题**:
- `updates.keys()` 直接拼入 SQL 列名
- 虽然调用方为内部代码，但接口设计不严谨
- 若 `updates` 被恶意构造，可注入任意列

**修复建议**:
```python
ALLOWED_UPDATE_FIELDS = {"display_name", "role", "enabled"}
for k in updates.keys():
    if k not in ALLOWED_UPDATE_FIELDS:
        raise ValueError(f"不允许更新字段: {k}")
```

**严重程度**: 🟡 Medium | **可利用**: Low (内部调用)

---

## 二、认证授权

### ✅ 已实现
- Session 管理 (7天过期, `secrets.token_urlsafe`)
- 密码 PBKDF2-HMAC-SHA256 (100000 次迭代)
- `hmac.compare_digest` 密码比较 (已修复 H-1)
- 账户锁定 (5次失败/30分钟)
- 多设备限制 (MAX_DEVICES_PER_USER = 3)
- Session 固定防护 (`regenerate=True`)
- RBAC 权限系统 (`@require_permission` 装饰器)

### 🟡 发现问题

#### A-1: `/collect` 无认证 — 已在上文 I-4 覆盖

---

#### A-2: CSRF 中间件不完整 — POST 可被绕过 ⚠️

**文件**: `app/middleware/csrf.py`

```python
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
if request.method in self.SAFE_METHODS:
    return await call_next(request)
client_token = request.headers.get("X-CSRF-Token") or request.cookies.get("csrf_token")
if not client_token:
    return JSONResponse(status_code=403, content={"error": "CSRF token required"})
```

**问题**:
- CSRF token 仅验证存在性，不验证正确性
- 攻击者只需在请求中带 `X-CSRF-Token: anything` 即可绕过
- Token 应该与服务端存储的值做比对

**修复建议**:
```python
async def dispatch(self, request: Request, call_next):
    if request.method in SAFE_METHODS:
        return await call_next(request)
    client_token = request.headers.get("X-CSRF-Token")
    server_token = request.cookies.get("csrf_token")
    if not hmac.compare_digest(client_token or "", server_token or ""):
        return JSONResponse(status_code=403, content={"error": "Invalid CSRF token"})
    return await call_next(request)
```

**严重程度**: 🟠 High | **可利用**: Yes

---

#### A-3: CSRF token 未设置 HttpOnly ⚠️

**问题**: 如果 CSRF token 存入 cookie，应设置 `HttpOnly=False` 以便 JS 读取，但需确保安全传输 (HTTPS + Secure)

---

#### A-4: 权限装饰器依赖 Header — 可被伪造 ⚠️

**文件**: `app/core/permissions.py`

```python
user_id = request.headers.get("X-User-ID")
```

**问题**:
- `X-User-ID` Header 完全由客户端控制
- `require_permission` 仅检查该 Header，未验证 session token
- 攻击者可伪造任意用户身份

**实际代码**:
```python
def require_permission(permission: Permission):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            user_id = None
            if request:
                user_id = getattr(request.state, "user_id", None)
                if not user_id:
                    user_id = request.headers.get("X-User-ID")  # ← 危险!
```

**修复建议**: 移除 Header 降级，只从 session 获取 user_id:
```python
if not user_id:
    raise HTTPException(status_code=401, detail="未认证")
```

**严重程度**: 🔴 Critical | **可利用**: Yes

---

#### A-5: `admin_users.json` 硬编码 admin 列表 ⚠️

**文件**: `app/core/permissions.py`

```python
ADMIN_FILE = Path(__file__).parent.parent.parent / "config" / "admin_users.json"
```

**问题**:
- 备份文件 (git历史、db_backups) 可能包含 admin 列表
- 建议使用数据库管理角色

**严重程度**: 🟡 Medium

---

## 三、敏感信息保护

### ✅ 已实现
- `SensitiveDataHandler` — 手机、邮箱、身份证脱敏
- `sanitize_log()` — 日志脱敏
- `mask_sensitive_data()` — 响应脱敏
- 数据库 backup 文件权限 `0600`
- `.env` 在 `.gitignore` 中

### 🔴 发现问题

#### S-1: `.env` 文件未被 git 追踪但内容泄露 ⚠️

**文件**: `.env`

```
N8N_WEBHOOK_KEY=n8n_secret_key_change_me
```

**问题**:
- 示例值 `n8n_secret_key_change_me` 被当作真实 key 使用 (注释说改，实际没改)
- `.gitignore` 已忽略 `.env`，但项目成员可能共享/泄露该文件

**严重程度**: 🟠 High

---

#### S-2: `harvest_api.py` 数据库 URL 含明文密码 ⚠️

**文件**: `app/api/harvest_api.py`

```python
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://scraper:changeme_pg_password_2026@localhost:5432/tender_scraper",
)
```

**问题**:
- 默认密码 `changeme_pg_password_2026` 硬编码在源码
- 若代码泄露，攻击者知道数据库连接信息

**严重程度**: 🟠 High

---

#### S-3: 收藏/导出接口返回完整数据 — 敏感字段可能泄露 ⚠️

**文件**: `app/api/routes/exports.py`

```python
rows = conn.execute(f"SELECT * FROM favorites WHERE {where} LIMIT 10000", params).fetchall()
```

**问题**:
- 直接返回 `SELECT *` 结果，若 `favorites` 表新增敏感字段会被暴露
- 前端未做字段过滤

**修复建议**:
```python
fields = ["title", "tender_type", "budget", "publish_date", "project_url", "status"]
rows = conn.execute(f"SELECT {','.join(fields)} FROM favorites WHERE {where} LIMIT 10000", params).fetchall()
```

**严重程度**: 🟡 Medium

---

#### S-4: Bot token 明文存储 ⚠️

**文件**: `app/api/routes/notifications_settings.py`

```python
nm.update_config(..., bot_token=bot_token, chat_id=chat_id, ...)
```

**问题**:
- Telegram Bot Token 明文存入 `settings.json`
- `settings.json` 未被 `.gitignore` 忽略

**严重程度**: 🟠 High

---

## 四、API 安全

### ✅ 已实现
- 安全响应头 (X-Frame-Options, HSTS, CSP)
- Rate Limiting 中间件 (100/min/IP)
- 请求 ID + 处理时间记录
- Pydantic Schema 验证
- Request ID 追踪

### 🔴 发现问题 (已在第一部分 I-2, I-3, I-4)

---

#### API-1: `/api/n8n/push-to-n8n` SSRF — 见 I-2
#### API-2: `/api/db/backup/download` 路径遍历 — 见 I-3
#### API-3: `/api/collect` 无认证 — 见 I-4
#### API-4: `/api/db/restore` 路径无校验 ⚠️

**文件**: `app/api/routes/database.py`

```python
@router.post("/restore")
def restore_backup(backup_path: str = Body(...)):
    success = get_db().restore_database(backup_path)
```

**问题**:
- 攻击者可指定任意文件路径进行"恢复"
- 可能覆盖任意文件

**修复**: 同 I-3 的路径校验

**严重程度**: 🟠 High | **可利用**: Yes (需管理员)

---

#### API-5: `/api/db/backup` 删除无校验 ⚠️

**文件**: `app/api/routes/database.py`

```python
@router.delete("/backup")
def delete_backup(backup_path: str = Body(...)):
    success = get_db().delete_db_backup(backup_path)
```

**问题**: 攻击者可能删除任意备份文件 (结合 I-3 路径遍历)

**严重程度**: 🟡 Medium | **可利用**: Yes (需管理员)

---

#### API-6: `n8n_api_key` 比较逻辑错误 ⚠️

**文件**: `app/api/routes_n8n.py`

```python
expected_key = os.getenv("N8N_WEBHOOK_KEY")
if not expected_key:
    raise ValueError("N8N_WEBHOOK_KEY 环境变量必须设置")  # ← raise ValueError?
if expected_key and x_n8n_webhook_key != expected_key:  # ← 第一个条件多余
    raise HTTPException(status_code=401, detail="Invalid webhook key")
```

**问题**:
- 若 `N8N_WEBHOOK_KEY` 未设置，抛出 `ValueError` 而非 `HTTPException`
- 这会导致 FastAPI 返回 500 错误而非 401，泄露内部错误信息
- 第二个条件 `expected_key and` 冗余

**修复建议**:
```python
expected_key = os.getenv("N8N_WEBHOOK_KEY", "")
if not expected_key:
    raise HTTPException(status_code=500, detail="Webhook 未配置")
if not hmac.compare_digest(x_n8n_webhook_key, expected_key):
    raise HTTPException(status_code=401, detail="Invalid webhook key")
```

**严重程度**: 🟡 Medium | **泄露**: 错误信息

---

## 五、依赖漏洞

### 关键依赖版本

| 包 | 版本 | 状态 |
|---|---|---|
| fastapi | 0.111.0 | ✅ 最新 |
| uvicorn | 0.30.0 | ⚠️ 有更新 |
| playwright | 1.44.0 | ⚠️ 有更新 |
| pydantic | 2.7.1 | ✅ 最新 |
| httpx | 0.27.0 | ✅ 最新 |
| asyncpg | 0.29.0 | ⚠️ 有更新 |
| redis | 5.0.6 | ⚠️ 有更新 |
| python-multipart | 0.0.9 | ⚠️ 有更新 |

### 🔴 发现问题

#### D-1: `requests` 库使用 ⚠️

**文件**: `app/api/routes/notifications.py`

```python
import requests
response = requests.post(...)
```

**问题**:
- `requests` 不推荐在新代码中使用 (同步、缺少现代 HTTP 支持)
- httpx 已在项目中使用，应统一
- requests 缺乏超时默认保护

**修复**: 替换为 httpx

**严重程度**: ⚪ Low

---

## 六、已修复 vs 已知问题状态

### ✅ 上次审计 (2026-04-05) 问题修复状态

| ID | 问题 | 状态 |
|---|---|---|
| H-1 | 时序攻击 (== → hmac.compare_digest) | ✅ **已修复** (`routes_users.py`) |
| H-2 | CSRF 中间件绕过 | ❌ **仍存在** — token 只验证存在，不验证值 |
| H-3 | 临时文件权限 | ❌ **未检查** |
| H-4 | traceback.print_exc | ✅ **已修复** (logger.exception) |
| H-5 | Session 固定攻击 | ✅ **已修复** (regenerate=True) |
| M-4 | 备份校验 SHA256 | ✅ **已修复** |
| M-5 | Health check | ✅ **已修复** |

### ❌ 仍存在的关键问题

1. **A-4**: `require_permission` 可通过伪造 `X-User-ID` Header 绕过认证 — 🔴 Critical
2. **I-2**: SSRF in `/push-to-n8n` — 🔴 Critical
3. **I-3**: 路径遍历 in `/db/backup/download` — 🔴 Critical
4. **I-4**: `/collect` 无认证 — 🟠 High
5. **A-2**: CSRF token 不验证值 — 🟠 High
6. **S-1**: 示例 webhook key 实际使用 — 🟠 High
7. **S-2**: DB URL 含明文密码 — 🟠 High

---

## 七、修复优先级

### 🔴 立即修复 (上线阻断)

| # | 问题 | 修复方案 |
|---|---|---|
| A-4 | `require_permission` X-User-ID 伪造 | 移除 Header 降级，只从 session 获取 user_id |
| I-2 | SSRF in push-to-n8n | 添加 URL 白名单验证 |
| I-3 | 路径遍历 in backup/download | 路径安全化 + 校验 |
| S-2 | DB URL 默认密码 | 移除硬编码默认密码 |

### 🟠 上线前修复

| # | 问题 |
|---|---|
| I-4 | `/collect` 无认证 |
| A-2 | CSRF token 不验证值 |
| S-1 | n8n webhook key 示例值 |
| S-4 | Bot token 明文存储 settings.json |
| I-1 | sanitize_input XSS 绕过 |

### 🟡 上线后 1 周

| # | 问题 |
|---|---|
| I-5 | update_user 动态列注入 |
| API-6 | ValueError vs HTTPException |
| D-1 | requests → httpx |
| A-3 | CSRF HttpOnly/Secure |

---

## 八、总结

**整体评价**: 项目已有较好的安全基础 (密码哈希、参数化查询、权限系统)，但存在 **3 个 Critical 漏洞** 和 **多个 High 漏洞** 需要修复才能安全上线。

**最紧急**:
1. A-4 (认证绕过) — 任何人可通过伪造 Header 冒充任意用户
2. I-2 (SSRF) — 内网探测和数据泄露
3. I-3 (路径遍历) — 任意文件读取

**建议**: 修复 Critical 问题后重新上线。
