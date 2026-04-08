"""DNS 泄漏防护 (DoH / DoT)"""

from typing import Dict, List, Tuple


class DNSLeakProtector:
    """
    DNS 泄漏防护模块。

    通过强制使用 DoH (DNS over HTTPS) 或 DoT (DNS over TLS)，
    防止本地 DNS 解析被 ISP/网络监控记录。

    支持公共 DoH/DoT 提供商（Google, Cloudflare, Quad9）。
    """

    DOH_PROVIDERS: Dict[str, str] = {
        "google":     "https://dns.google/dns-query",
        "cloudflare": "https://cloudflare-dns.com/dns-query",
        "quad9":      "https://dns.quad9.net/dns-query",
        "ali":        "https://dns.alidns.com/dns-query",       # 阿里云 DoH（国内低延迟）
    }

    DOT_PROVIDERS: Dict[str, Tuple[str, int]] = {
        "google":     ("dns.google",         853),
        "cloudflare": ("cloudflare-dns.com", 853),
        "quad9":      ("dns.quad9.net",       853),
        "ali":       ("dns.alidns.com",      853),
    }

    def __init__(
        self,
        provider: str = "cloudflare",
        mode: str = "doh",   # "doh" | "dot"
    ):
        if provider not in self.DOH_PROVIDERS:
            raise ValueError(f"Unknown DoH provider: {provider}")
        if mode not in ("doh", "dot"):
            raise ValueError(f"mode must be 'doh' or 'dot', got {mode}")

        self.provider = provider
        self.mode     = mode

    @property
    def doh_url(self) -> str:
        return self.DOH_PROVIDERS[self.provider]

    @property
    def dot_endpoint(self) -> Tuple[str, int]:
        return self.DOT_PROVIDERS[self.provider]

    def get_systemd_resolved_config(self) -> str:
        """
        生成 systemd-resolved 的 DoH/DoT 配置片段。
        适用于 Linux 系统。
        """
        if self.mode == "doh":
            return f"""[Resolve]
DNS={self.dot_endpoint[0]}:{self.dot_endpoint[1]}
DNSOverTLS={self.provider}
Domains=~."""
        return f"""[Resolve]
DNS={self.DOH_PROVIDERS[self.provider]}
DNSOverHTTPS=yes
Domains=~."""

    def get_httpx_doh_session_config(self) -> Dict[str, str]:
        """
        为 httpx 提供 DoH 配置（通过 httpx.AsyncHTTPTransport + DoH）。
        用法：
          import httpx
          transport = httpx.AsyncHTTPTransport(retries=3)
          client = httpx.AsyncClient(transport=transport,
                                     verify=False,
                                     timeout=10.0)
          client.get("https://example.com",
                     headers={"Accept": "application/dns-message"},
                     # 配合系统 DNS 劫持 / /etc/hosts 强制 DoH）
        """
        return {
            "provider": self.provider,
            "doh_url":  self.doh_url,
        }

    def build_hosts_blocklist(self) -> List[str]:
        """
        生成需要强制走 DoH 的域名列表（防止 DNS 泄漏到直连 DNS）。
        采集目标域名优先走 DoH。
        """
        return [
            "ccgp-chongqing.gov.cn",
            "cqggzy.gov.cn",
            "ccgp.gov.cn",
            "gjzfcg.gov.cn",
        ]
