"""LLM 多模型服务 — 支持重试 + 自动切换 + 连接池化"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

# ── 共享 aiohttp Session（连接池复用，避免每请求新建）───────
_aiohttp_session: Optional[Any] = None


async def _get_aiohttp_session() -> Any:
    """获取共享 aiohttp ClientSession（连接池复用）"""
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        import aiohttp
        connector = aiohttp.TCPConnector(
            limit=20,          # 最大并发连接数
            limit_per_host=10,  # 每个 host 最大连接
            ttl_dns_cache=300, # DNS 缓存 5 分钟
        )
        _aiohttp_session = aiohttp.ClientSession(connector=connector)
        logger.info("[llm] aiohttp session pool initialized: limit=20, per_host=10")
    return _aiohttp_session


async def close_aiohttp_session():
    """关闭共享 aiohttp session（应用退出时调用）"""
    global _aiohttp_session
    if _aiohttp_session is not None and not _aiohttp_session.closed:
        await _aiohttp_session.close()
        _aiohttp_session = None
        logger.info("[llm] aiohttp session closed")


# ── Provider 类型常量 ──────────────────────────────────────
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OLLAMA = "ollama"
PROVIDER_QWEN = "qwen"          # 阿里通义
PROVIDER_MINIMAX = "minimax"    # MiniMax

# MiniMax 可用模型列表
MINIMAX_MODELS = (
    "MiniMax-M2",           # 对话/编码模型 (默认)
    "MiMo-V2.5-Pro",        # 小米 MiMo-V2.5-Pro 推理模型
    "MiMo-V2.5",            # 小米 MiMo-V2.5 基础模型
    "coding-plan-vlm",     # 图片理解 VLM (Coding Plan)
    "image-01",            # 图片生成模型
    "lyrics_generation",   # 歌词生成模型
    "MiMo-V2.5-TTS-VoiceClone",  # TTS 语音克隆模型
)

# 模型用途分类
MINIMAX_CHAT_MODELS = ("MiniMax-M2", "MiMo-V2.5-Pro", "MiMo-V2.5")  # 对话模型
MINIMAX_IMAGE_UNDERSTAND_MODELS = ("coding-plan-vlm",)  # 图片理解
MINIMAX_IMAGE_GENERATION_MODELS = ("image-01",)     # 图片生成
MINIMAX_MUSIC_MODELS = ("lyrics_generation",)       # 音乐/歌词生成
MINIMAX_TTS_MODELS = ("MiMo-V2.5-TTS-VoiceClone",)  # TTS 语音克隆

PROVIDER_RAGFLOW = "ragflow"
PROVIDER_NONE = "none"


@dataclass
class LLMResponse:
    """LLM 调用结果"""
    content: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.content)


@dataclass
class LLMProviderConfig:
    """单个 LLM Provider 配置"""
    name: str                     # 显示名称，如 "OpenAI-GPT4"
    provider_type: str            # openai / anthropic / ollama / qwen / minimax / ragflow / none
    api_key: str = ""
    base_url: str = ""           # 代理 URL 或自托管端点
    model: str = "gpt-4o-mini"  # 默认模型
    max_retries: int = 3         # 单 provider 最大重试次数
    timeout: int = 60             # 超时（秒）
    enabled: bool | None = None  # None = auto（根据 api_key 自动判断）

    def __post_init__(self):
        # 自动判断：None 时按 api_key 有无自动决定 enabled
        if self.enabled is None:
            self.enabled = bool(self.api_key) or self.provider_type in (PROVIDER_NONE, PROVIDER_OLLAMA)


class LLMService:
    """
    多模型 LLM 服务

    特性：
    - 多 Provider 链式调用（自动切换）
    - 指数退避重试
    - 流量限制检测 + 等待
    - 统一响应格式
    """

    def __init__(self, providers: list[LLMProviderConfig] = None):
        """
        Args:
            providers: Provider 列表，按优先级排序。第一个为主用，其余为 fallback。
        """
        self.providers = providers or []
        self._client_cache: dict = {}

    # ── 配置加载 ──────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "LLMService":
        """从环境变量构建默认单 Provider 配置"""
        provider_type = os.getenv("LLM_PROVIDER", PROVIDER_NONE)
        if provider_type == PROVIDER_NONE:
            return cls([])

        api_key = cls._get_api_key(provider_type)
        base_url = cls._get_base_url(provider_type)
        model = os.getenv("LLM_MODEL", cls._default_model(provider_type))

        provider = LLMProviderConfig(
            name=f"{provider_type.upper()}-{model}",
            provider_type=provider_type,
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_retries=3,
        )
        return cls([provider] if provider.enabled else [])

    @classmethod
    def from_config_list(cls, configs: list[dict]) -> "LLMService":
        """从配置列表构建多 Provider 配置"""
        providers = [
            LLMProviderConfig(
                name=c.get("name", c["provider_type"]),
                provider_type=c["provider_type"],
                api_key=c.get("api_key", ""),
                base_url=c.get("base_url", ""),
                model=c.get("model", cls._default_model(c["provider_type"])),
                max_retries=c.get("max_retries", 3),
                timeout=c.get("timeout", 60),
                enabled=c.get("enabled", True),
            )
            for c in configs
        ]
        return cls([p for p in providers if p.enabled])

    @staticmethod
    def _get_api_key(provider_type: str) -> str:
        keys = {
            PROVIDER_OPENAI: "OPENAI_API_KEY",
            PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
            PROVIDER_QWEN: "DASHSCOPE_API_KEY",
            PROVIDER_MINIMAX: "MINIMAX_API_KEY",
        }
        return os.getenv(keys.get(provider_type, ""), "")

    @staticmethod
    def _get_base_url(provider_type: str) -> str:
        urls = {
            PROVIDER_OPENAI: os.getenv("OPENAI_BASE_URL", ""),
            PROVIDER_ANTHROPIC: os.getenv("ANTHROPIC_BASE_URL", ""),
            PROVIDER_QWEN: os.getenv("DASHSCOPE_BASE_URL", ""),
            PROVIDER_MINIMAX: os.getenv("MINIMAX_BASE_URL", ""),
        }
        return urls.get(provider_type, "")

    @staticmethod
    def _default_model(provider_type: str) -> str:
        models = {
            PROVIDER_OPENAI: "gpt-4o-mini",
            PROVIDER_ANTHROPIC: "claude-sonnet-4-20250514",
            PROVIDER_OLLAMA: "llama3",
            PROVIDER_QWEN: "qwen-plus",
            PROVIDER_MINIMAX: "MiniMax-M2",
            PROVIDER_RAGFLOW: "",
        }
        return models.get(provider_type, "gpt-4o-mini")

    # ── 核心调用 ──────────────────────────────────────────

    async def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """
        发送对话请求，自动重试 + 切换 Provider

        Args:
            prompt: 用户输入
            system_prompt: 系统提示
            json_mode: 是否要求 JSON 输出
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLMResponse（成功时 content 有值，失败时 error 有值）
        """
        errors = []

        for provider in self.providers:
            if not provider.enabled:
                continue

            result = await self._call_with_retry(
                provider, prompt, system_prompt, json_mode, temperature, max_tokens
            )
            if result.success:
                return result
            errors.append(f"[{provider.name}] {result.error}")

        # 所有 provider 都失败
        return LLMResponse(
            content="",
            provider="",
            model="",
            error=f"All providers failed: {'; '.join(errors)}",
        )

    async def _call_with_retry(
        self,
        provider: LLMProviderConfig,
        prompt: str,
        system_prompt: str,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """单个 Provider 调用，带指数退避重试"""
        base_delay = 2  # 秒
        last_error = None

        for attempt in range(provider.max_retries):
            start = time.monotonic()
            try:
                content = await self._dispatch(provider, prompt, system_prompt, json_mode, temperature, max_tokens)
                latency_ms = int((time.monotonic() - start) * 1000)
                return LLMResponse(
                    content=content,
                    provider=provider.name,
                    model=provider.model,
                    latency_ms=latency_ms,
                )
            except RateLimitError as e:
                # 429：长时间退避
                wait = e.retry_after or base_delay * (2 ** attempt) * 3
                logger.warning(f"[{provider.name}] Rate limited, waiting {wait:.0f}s (attempt {attempt+1}/{provider.max_retries})")
                await asyncio.sleep(wait)
                last_error = f"rate limited, waited {wait:.0f}s"
            except RetryableError as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[{provider.name}] Retryable error: {e}, retrying in {delay}s (attempt {attempt+1}/{provider.max_retries})")
                await asyncio.sleep(delay)
                last_error = str(e)
            except NonRetryableError as e:
                # 认证失败、权限错误等，不重试直接切换
                logger.error(f"[{provider.name}] Non-retryable error: {e}")
                return LLMResponse(content="", provider=provider.name, model=provider.model, error=str(e))
            except Exception as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[{provider.name}] Error: {e}, retrying in {delay}s (attempt {attempt+1}/{provider.max_retries})")
                await asyncio.sleep(delay)
                last_error = str(e)

        return LLMResponse(
            content="",
            provider=provider.name,
            model=provider.model,
            error=f"max retries ({provider.max_retries}) exceeded: {last_error}",
        )

    async def _dispatch(
        self,
        provider: LLMProviderConfig,
        prompt: str,
        system_prompt: str,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """根据 provider_type 分发到对应实现"""
        dispatch_map = {
            PROVIDER_OPENAI: self._call_openai,
            PROVIDER_ANTHROPIC: self._call_anthropic,
            PROVIDER_OLLAMA: self._call_ollama,
            PROVIDER_QWEN: self._call_qwen,
            PROVIDER_MINIMAX: self._call_minimax,
            PROVIDER_RAGFLOW: self._call_ragflow,
        }
        fn = dispatch_map.get(provider.provider_type)
        if not fn:
            raise NonRetryableError(f"Unknown provider type: {provider.provider_type}")
        return await fn(provider, prompt, system_prompt, json_mode, temperature, max_tokens)

    # ── 各 Provider 实现 ──────────────────────────────────

    async def _call_openai(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        import openai

        client_kwargs = {"api_key": p.api_key, "timeout": p.timeout}
        if p.base_url:
            client_kwargs["base_url"] = p.base_url

        client = openai.OpenAI(**client_kwargs)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": p.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except openai.RateLimitError as e:
            raise RateLimitError(str(e), retry_after=self._extract_retry_after(e))
        except openai.AuthenticationError as e:
            raise NonRetryableError(f"auth failed: {e}")
        except openai.BadRequestError as e:
            raise NonRetryableError(f"bad request: {e}")
        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(str(e))
            raise RetryableError(str(e))

    async def _call_anthropic(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        import anthropic

        client_kwargs = {"api_key": p.api_key, "timeout": p.timeout}
        if p.base_url:
            client_kwargs["base_url"] = p.base_url

        client = anthropic.Anthropic(**client_kwargs)

        system_msg = system if system else None
        resp = client.messages.create(
            model=p.model,
            max_tokens=max_tokens,
            system=system_msg,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return resp.content[0].text

    async def _call_ollama(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        import aiohttp

        base = p.base_url or "http://localhost:11434"
        url = f"{base}/api/chat"
        payload = {
            "model": p.model,
            "messages": [
                *( [{"role": "system", "content": system}] if system else []),
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with (await _get_aiohttp_session()) as sess:
            async with sess.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=p.timeout)) as resp:
                if resp.status == 429:
                    raise RateLimitError("ollama rate limited")
                if resp.status != 200:
                    text = await resp.text()
                    raise NonRetryableError(f"ollama {resp.status}: {text}")
                data = await resp.json()
                return data["message"]["content"]

    async def _call_qwen(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        """阿里通义千问（DashScope）"""
        import aiohttp

        api_key = p.api_key or os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise NonRetryableError("DASHSCOPE_API_KEY not set")

        url = p.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": p.model,
            "messages": [
                *( [{"role": "system", "content": system}] if system else []),
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with (await _get_aiohttp_session()) as sess:
            async with sess.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=p.timeout)) as resp:
                if resp.status == 429:
                    raise RateLimitError("qwen rate limited")
                if resp.status == 401:
                    raise NonRetryableError("qwen auth failed: invalid API key")
                if resp.status != 200:
                    text = await resp.text()
                    raise RetryableError(f"qwen {resp.status}: {text}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    async def _call_minimax(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        """MiniMax API"""
        import aiohttp

        api_key = p.api_key or os.getenv("MINIMAX_API_KEY", "")
        if not api_key:
            raise NonRetryableError("MINIMAX_API_KEY not set")

        url = p.base_url or "https://api.minimax.chat/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": p.model,
            "messages": [
                *( [{"role": "system", "content": system}] if system else []),
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with (await _get_aiohttp_session()) as sess:
            async with sess.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=p.timeout)) as resp:
                if resp.status == 429:
                    raise RateLimitError("minimax rate limited")
                if resp.status == 401:
                    raise NonRetryableError("minimax auth failed")
                if resp.status != 200:
                    text = await resp.text()
                    raise RetryableError(f"minimax {resp.status}: {text}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

    async def _call_ragflow(
        self, p: LLMProviderConfig,
        prompt: str, system: str, json_mode: bool,
        temperature: float, max_tokens: int,
    ) -> str:
        """RAGFlow API（复用 document_analyzer 的逻辑）"""
        # RAGFlow 通过 MCP 或直接 HTTP 调用
        # 这里简化处理：直接调用已配置的 RAGFlow MCP URL
        raise NonRetryableError("RAGFlow provider not yet implemented via LLMService")

    # ── 辅助 ──────────────────────────────────────────────

    @staticmethod
    def _extract_retry_after(exc) -> Optional[int]:
        """从异常中提取 Retry-After 秒数"""
        if hasattr(exc, "response") and exc.response is not None:
            return int(exc.response.headers.get("Retry-After", 60))
        return None


# ── 异常层次 ──────────────────────────────────────────────

class LLMError(Exception):
    """基础异常"""
    pass

class RateLimitError(LLMError):
    """Rate limit (429)，需要长等待"""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after

class RetryableError(LLMError):
    """可重试错误（超时、服务器错误等）"""
    pass

class NonRetryableError(LLMError):
    """不可重试错误（认证、参数等），直接切换 Provider"""
    pass


# ── 全局单例 ─────────────────────────────────────────────

_global_llm_service: Optional["LLMService"] = None
_llm_service_lock = asyncio.Lock()


def get_llm_service_sync() -> "LLMService":
    """同步版本 - 返回已初始化的实例（不触发初始化）"""
    return _global_llm_service


async def get_llm_service() -> "LLMService":
    """获取全局 LLM Service 实例（线程安全）"""
    global _global_llm_service
    if _global_llm_service is not None:
        return _global_llm_service

    async with _llm_service_lock:
        if _global_llm_service is not None:
            return _global_llm_service

        providers = _load_llm_providers_from_file()
        _global_llm_service = LLMService.from_config_list(providers)
        logger.info(f"LLM service initialized with {len(_global_llm_service.providers)} providers")
        return _global_llm_service


def reload_llm_service() -> "LLMService":
    """重新加载配置（同步，供热更新用）"""
    global _global_llm_service
    providers = _load_llm_providers_from_file()
    _global_llm_service = LLMService.from_config_list(providers)
    logger.info(f"LLM service reloaded with {len(_global_llm_service.providers)} providers")
    return _global_llm_service


def _load_llm_providers_from_file() -> list:
    """从配置文件加载 Provider 列表"""
    import pathlib
    SYS_PATH = pathlib.Path(__file__).parent.parent.parent
    config_path = SYS_PATH / "config" / "llm_providers.json"
    if not config_path.exists():
        provider_type = os.getenv("LLM_PROVIDER", "openai")
        if provider_type == "none":
            return []
        return [{
            "name": f"{provider_type}-default",
            "provider_type": provider_type,
            "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "api_key": _get_env_key(provider_type),
            "base_url": _get_env_url(provider_type),
            "max_retries": 3,
            "timeout": 60,
            "enabled": True,
        }]
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return []


def _get_env_key(provider_type: str) -> str:
    keys = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }
    return os.getenv(keys.get(provider_type, ""), "")


def _get_env_url(provider_type: str) -> str:
    urls = {
        "openai": "OPENAI_BASE_URL",
        "anthropic": "ANTHROPIC_BASE_URL",
        "qwen": "DASHSCOPE_BASE_URL",
        "minimax": "MINIMAX_BASE_URL",
    }
    return os.getenv(urls.get(provider_type, ""), "")
