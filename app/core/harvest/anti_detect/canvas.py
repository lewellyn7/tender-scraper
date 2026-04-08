"""Canvas 指纹噪声注入与 WebGL 参数伪造"""

import random
from typing import Optional


class CanvasNoiseInjector:
    """
    通过 Playwright CDP (DevTools) 协议劫持 WebGL / Canvas API，
    在渲染时注入不可察觉的随机噪声。

    原理：重写 `HTMLCanvasElement.prototype.getContext` 和
         `WebGLRenderingContext` 的 `getExtension` / `getParameter`，
         在像素级别注入小幅随机偏移（肉眼不可见，bot 检测可识别）。
    """

    CANVAS_NOISE_JS = r"""
    (function() {
        'use strict';

        const NOISE_SCALE = %f;  // 注入时传入
        const _origGetContext = HTMLCanvasElement.prototype.getContext;

        function _addNoiseToImageData(imageData) {
            const data = imageData.data;
            const len  = data.length;
            for (let i = 0; i < len; i += 4) {
                // 对 RGB 注入小幅噪声，A 通道不变
                data[i]     = Math.min(255, Math.max(0, data[i]     + (Math.random() - 0.5) * NOISE_SCALE * 255));
                data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + (Math.random() - 0.5) * NOISE_SCALE * 255));
                data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + (Math.random() - 0.5) * NOISE_SCALE * 255));
            }
            return imageData;
        }

        // 劫持 2D canvas getContext
        HTMLCanvasElement.prototype.getContext = function(type, attrs) {
            const ctx = _origGetContext.call(this, type, attrs);
            if (type === '2d') {
                const _origGetImageData = ctx.getImageData.bind(ctx);
                ctx.getImageData = function(sx, sy, sw, sh) {
                    const imgData = _origGetImageData(sx, sy, sw, sh);
                    return _addNoiseToImageData(imgData);
                };
            }
            return ctx;
        };

        // 劫持 WebGLRenderingContext.getParameter（伪造 GPU 指纹）
        const _origGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {
            // WEBGL_debug_renderer_info 扩展：隐藏真实 GPU
            if (p === 37445) return 'Google Inc. (NVIDIA)';      // UNMASKED_VENDOR
            if (p === 37446) return 'ANGLE (NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)'; // UNMASKED_RENDERER
            return _origGetParameter.call(this, p);
        };

        // 随机化 WebGL 随机种子（部分网站检测 Math.random 一致性）
        const _origRandom = Math.random;
        let _randomEpoch  = %d;   // 注入随机种子
        Math.random = function() {
            _randomEpoch = (_randomEpoch * 1664525 + 1013904223) & 0xffffffff;
            return (_randomEpoch >>> 0) / 4294967296;
        };
    })();
    """

    def __init__(self, noise_scale: float = 0.0005, seed: Optional[int] = None):
        self.noise_scale = noise_scale
        self.seed = seed or random.randint(0, 2**31 - 1)

    def get_injection_script(self) -> str:
        return self.CANVAS_NOISE_JS % (self.noise_scale, self.seed)

    async def inject(self, page) -> None:
        """将噪声 JS 注入到 Playwright page."""
        await page.add_init_script(self.get_injection_script())
