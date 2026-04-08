"""WebGL 指纹检测与防护

注意: WebGL 指纹伪造已整合到 CanvasNoiseInjector (canvas.py) 中，
通过劫持 WebGLRenderingContext.prototype.getParameter 实现：
  - 37445 (UNMASKED_VENDOR_WEBGL) → 伪装 GPU 供应商
  - 37446 (UNMASKED_RENDERER_WEBGL) → 伪装 GPU 渲染器
"""

# WebGL 指纹参数常量
UNMASKED_VENDOR_WEBGL = 37445
UNMASKED_RENDERER_WEBGL = 37446

# 伪装 GPU 池（与 FingerprintProfile.WEBGL_POOL 保持同步）
FAKE_GPU_POOL = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (Intel)", "ANGLE (Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (AMD)", "ANGLE (AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (Intel)", "ANGLE (Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)"),
    ("Intel Inc.", "Intel Iris OpenGL Engine"),
]
