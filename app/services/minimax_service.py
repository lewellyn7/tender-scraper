"""MiniMax 多模态服务 — 图片理解/生成、歌词/音乐生成、文本嵌入"""
import os
import math
from dataclasses import dataclass
from typing import List, Optional, Union

import aiohttp
from loguru import logger


@dataclass
class MiniMaxResponse:
    """MiniMax API 响应"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


def cosine_sim(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MiniMaxService:
    """MiniMax 多模态服务"""
    
    BASE_URL = "https://api.minimaxi.com"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url = os.getenv("MINIMAX_BASE_URL", self.BASE_URL)
    
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def understand_image(
        self,
        prompt: str,
        image_url: str,
        model: str = "coding-plan-vlm",
    ) -> MiniMaxResponse:
        """图片理解 (Vision)
        
        Args:
            prompt: 图片理解指令/问题
            image_url: 图片 URL 或本地文件路径
            model: 模型名 (默认 coding-plan-vlm)
        
        Returns:
            MiniMaxResponse with understanding result
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        
        url = f"{self.base_url}/v1/images/understand"
        payload = {
            "model": model,
            "prompt": prompt,
            "image_url": image_url,
        }
        
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    return MiniMaxResponse(success=True, data=data)
        except Exception as e:
            logger.error(f"[minimax] understand_image failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))
    
    async def generate_image(
        self,
        prompt: str,
        model: str = "image-01",
        aspect_ratio: str = "1:1",
        style: dict = None,
        subject_reference: list = None,
    ) -> MiniMaxResponse:
        """图片生成 (Text-to-Image)
        
        Args:
            prompt: 图片描述文本 (最长 1500 字符)
            model: 模型名 (默认 image-01)
            aspect_ratio: 宽高比 (1:1, 3:4, 4:3, 9:16, 16:9)
            style: 画风设置 (仅 image-01-live)
            subject_reference: 人物主体参考 (用于图生图)
        
        Returns:
            MiniMaxResponse with generated image info
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        
        url = f"{self.base_url}/v1/image_generation"
        payload = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }
        if style:
            payload["style"] = style
        if subject_reference:
            payload["subject_reference"] = subject_reference
        
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    return MiniMaxResponse(success=True, data=data)
        except Exception as e:
            logger.error(f"[minimax] generate_image failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))
    
    async def image_to_image(
        self,
        prompt: str,
        image_url: str,
        model: str = "image-01",
        style: dict = None,
        subject_reference: list = None,
    ) -> MiniMaxResponse:
        """图生图 (Image-to-Image)
        
        Args:
            prompt: 图片描述文本
            image_url: 输入图片 URL
            model: 模型名 (默认 image-01)
            style: 画风设置
            subject_reference: 人物主体参考
        
        Returns:
            MiniMaxResponse with generated image info
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        
        url = f"{self.base_url}/v1/image_generation"
        payload = {
            "model": model,
            "prompt": prompt,
            "image_url": image_url,
        }
        if style:
            payload["style"] = style
        if subject_reference:
            payload["subject_reference"] = subject_reference
        
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    return MiniMaxResponse(success=True, data=data)
        except Exception as e:
            logger.error(f"[minimax] image_to_image failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))
    
    async def generate_lyrics(
        self,
        mode: str = "write_full_song",
        prompt: str = "",
        lyrics: str = None,
        title: str = None,
    ) -> MiniMaxResponse:
        """歌词生成
        
        Args:
            mode: 生成模式 (write_full_song=完整歌曲, edit=编辑/续写)
            prompt: 歌曲主题/风格描述 (为空时随机生成)
            lyrics: 现有歌词 (仅 edit 模式)
            title: 歌曲标题 (传入后保持该标题)
        
        Returns:
            MiniMaxResponse with generated lyrics
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        
        if mode not in ("write_full_song", "edit"):
            return MiniMaxResponse(success=False, error="mode must be 'write_full_song' or 'edit'")
        
        url = f"{self.base_url}/v1/lyrics_generation"
        payload = {
            "mode": mode,
            "prompt": prompt,
        }
        if lyrics:
            payload["lyrics"] = lyrics
        if title:
            payload["title"] = title
        
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    return MiniMaxResponse(success=True, data=data)
        except Exception as e:
            logger.error(f"[minimax] generate_lyrics failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))
    
    async def generate_music(
        self,
        prompt: str,
        lyrics: str = None,
        title: str = None,
        model: str = "music-2.6",
    ) -> MiniMaxResponse:
        """音乐生成
        
        Args:
            prompt: 歌曲描述 (风格、情绪、乐器等)
            lyrics: 歌词 (可选，不提供则纯器乐)
            title: 歌曲标题
            model: 模型名 (默认 music-2.6)
        
        Returns:
            MiniMaxResponse with generated music info
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        
        url = f"{self.base_url}/v1/music_generation"
        payload = {
            "model": model,
            "prompt": prompt,
        }
        if lyrics:
            payload["lyrics"] = lyrics
        if title:
            payload["title"] = title
        
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    return MiniMaxResponse(success=True, data=data)
        except Exception as e:
            logger.error(f"[minimax] generate_music failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))

    async def embed_texts(self, texts: List[str], model: str = "embza-base") -> MiniMaxResponse:
        """文本嵌入 — 批量版本

        Args:
            texts: 文本列表（单条不超过 512 tokens）
            model: 嵌入模型，默认 embza-base
        Returns:
            MiniMaxResponse(data={{ "embeddings": [[float, ...], ...], "tokens": int }})
        """
        if not self.api_key:
            return MiniMaxResponse(success=False, error="MINIMAX_API_KEY not set")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{self.base_url}/v1/text/embeddings",
                    headers=self._headers(),
                    json={"model": model, "texts": texts},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return MiniMaxResponse(success=False, error=f"API error {resp.status}: {text}")
                    data = await resp.json()
                    embeddings = data.get("data", {}).get("result", {}).get("embeddings", [])
                    return MiniMaxResponse(success=True, data={"embeddings": embeddings, "tokens": data.get("data", {}).get("tokens_used", 0)})
        except Exception as e:
            logger.error(f"[minimax] embed_texts failed: {e}")
            return MiniMaxResponse(success=False, error=str(e))

    async def embed_text(self, text: str, model: str = "embza-base") -> MiniMaxResponse:
        """单条文本嵌入"""
        return await self.embed_texts([text], model=model)


# 全局单例
_minimax_service: Optional[MiniMaxService] = None


def get_minimax_service() -> MiniMaxService:
    global _minimax_service
    if _minimax_service is None:
        _minimax_service = MiniMaxService()
    return _minimax_service
