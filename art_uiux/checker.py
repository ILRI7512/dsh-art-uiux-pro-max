"""访问探测：robots.txt → HTTP → 分类结论。

对应需求四的访问策略：
- 先读 robots.txt，被禁止就记 ``blocked``，**不绕过**；
- 401/403/402/429 → ``restricted``（需登录/付费/限流），不尝试绕过；
- 2xx → ``reachable``，但不代表已学习；
- 4xx/5xx/超时 → ``failed``，保留错误原文；
- 只读有限字节（默认 256 KB），不下载媒体。
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

UA = "DSH-Art-UIUX-ProMax/1.0 (+local design research agent; respects robots.txt)"
MAX_BYTES = 256 * 1024
ROBOTS_TTL_S = 3600

_robots_cache: Dict[str, Tuple[float, Optional[urllib.robotparser.RobotFileParser]]] = {}
_robots_lock = threading.Lock()
_host_next_slot: Dict[str, float] = {}
_host_lock = threading.Lock()
HOST_MIN_INTERVAL_S = 0.8


@dataclass
class ProbeResult:
    url: str
    access_status: str
    http_status: Optional[int] = None
    final_url: str = ""
    content_type: str = ""
    bytes_read: int = 0
    robots_allowed: Optional[bool] = None
    title: str = ""
    error: str = ""


def _throttle(host: str) -> None:
    """同一 host 的最小请求间隔，避免被判定为 abusive。"""

    with _host_lock:
        now = time.monotonic()
        wait = _host_next_slot.get(host, 0.0) - now
        _host_next_slot[host] = max(now, _host_next_slot.get(host, 0.0)) + HOST_MIN_INTERVAL_S
    if wait > 0:
        time.sleep(min(wait, 3.0))


def _robots_for(host_url: str, client: httpx.Client) -> Optional[urllib.robotparser.RobotFileParser]:
    with _robots_lock:
        cached = _robots_cache.get(host_url)
        if cached and (time.time() - cached[0]) < ROBOTS_TTL_S:
            return cached[1]
    parser: Optional[urllib.robotparser.RobotFileParser] = None
    try:
        resp = client.get(host_url.rstrip("/") + "/robots.txt", timeout=15)
        if resp.status_code == 200:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(resp.text.splitlines())
        elif resp.status_code in (404, 410):
            parser = None  # 无 robots.txt：视为未禁止
    except Exception:
        parser = None
    with _robots_lock:
        _robots_cache[host_url] = (time.time(), parser)
    return parser


def probe(url: str, client: Optional[httpx.Client] = None, *, timeout: float = 20.0) -> ProbeResult:
    own_client = client is None
    client = client or httpx.Client(follow_redirects=True, headers={"User-Agent": UA})
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return ProbeResult(url=url, access_status="failed", error="不支持的协议: %s" % parts.scheme)
        host_url = "%s://%s" % (parts.scheme, parts.netloc)
        _throttle(parts.netloc)
        parser = _robots_for(host_url, client)
        allowed = True
        if parser is not None:
            allowed = parser.can_fetch(UA, url)
            if not allowed:
                return ProbeResult(url=url, access_status="blocked", robots_allowed=False,
                                   error="robots.txt 禁止抓取该路径")
        _throttle(parts.netloc)
        with client.stream("GET", url, timeout=timeout) as resp:
            status = resp.status_code
            final_url = str(resp.url)
            ctype = resp.headers.get("content-type", "")
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) >= MAX_BYTES:
                    break
            text = body.decode("utf-8", errors="ignore")
            title = ""
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()[:160]
            if 200 <= status < 300:
                access = "reachable"
                # 2xx 但响应体几乎为空：常见于反爬/软拦截（例如 HTTP 202 + 空 body），
                # 不能算「可访问」，否则就是把假成功写进注册表。
                if len(body) < 200:
                    access = "restricted"
            elif status in (401, 402, 403, 429):
                access = "restricted"
            else:
                access = "failed"
            return ProbeResult(
                url=url, access_status=access, http_status=status, final_url=final_url,
                content_type=ctype, bytes_read=len(body), robots_allowed=allowed,
                title=title, error="" if access == "reachable" else "HTTP %s" % status,
            )
    except httpx.TimeoutException:
        return ProbeResult(url=url, access_status="failed", robots_allowed=None, error="超时")
    except httpx.HTTPError as exc:
        return ProbeResult(url=url, access_status="failed", robots_allowed=None, error="%s: %s" % (type(exc).__name__, exc))
    except Exception as exc:  # noqa: BLE001 - 探测阶段任何异常都要如实记录
        return ProbeResult(url=url, access_status="failed", robots_allowed=None, error="%s: %s" % (type(exc).__name__, exc))
    finally:
        if own_client:
            client.close()


def probe_many(urls: List[str], *, workers: int = 6) -> List[ProbeResult]:
    results: List[ProbeResult] = []
    with httpx.Client(follow_redirects=True, headers={"User-Agent": UA}) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(probe, url, client) for url in urls]
            for fut in futures:
                results.append(fut.result())
    return results
