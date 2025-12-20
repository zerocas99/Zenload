"""Lightweight proxy provider used to bypass simple geo/rate limits.

The provider keeps a short-lived cache of HTTP/HTTPS proxies fetched from
public lists (proxyscrape, JetKai). We only fetch on demand and randomize
results to avoid hammering the same endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class ProxyProvider:
    """Fetch and cache public proxies."""

    def __init__(self) -> None:
        self._cache: Dict[str, List[str]] = {}
        self._cache_ts: Dict[str, float] = {}
        # Allow overriding sources from env if needed
        extra_sources = os.getenv("PROXY_SOURCES", "")
        extra_list = [s.strip() for s in extra_sources.split(",") if s.strip()]
        self._sources_default = [
            "https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=7000&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
        ] + extra_list
        # Optional local file with curated proxies (e.g., proxies.json in repo root)
        self._local_proxy_file = Path(os.getenv("PROXY_FILE", "proxies.json"))
        # Use a small whitelist of typical HTTP/HTTPS ports
        self._allowed_ports = {
            "80",
            "81",
            "88",
            "1080",
            "3128",
            "3129",
            "443",
            "8000",
            "8008",
            "8080",
            "8081",
            "8082",
            "8083",
            "8085",
            "8090",
            "8443",
            "8888",
            "9090",
            "10000",
        }

    def _needs_refresh(self, key: str) -> bool:
        ttl = 1800  # 30 minutes
        return key not in self._cache or time.time() - self._cache_ts.get(key, 0) > ttl

    def _load_local_file(self) -> List[str]:
        if not self._local_proxy_file.exists():
            return []
        try:
            text = self._local_proxy_file.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(text)
            proxies: List[str] = []
            if isinstance(data, list):
                for entry in data:
                    if not isinstance(entry, dict):
                        continue
                    host = str(entry.get("ip_address") or entry.get("ip") or "").strip()
                    port = str(entry.get("port") or "").strip()
                    if host and port and port.isdigit() and port in self._allowed_ports:
                        proxies.append(f"{host}:{port}")
            random.shuffle(proxies)
            # Keep only a small curated slice to avoid hammering low-quality proxies
            return proxies[:50]
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ProxyProvider] Could not load local proxy file: {e}")
            return []

    def _fetch(self, country: Optional[str]) -> List[str]:
        """Fetch proxies and return list of host:port strings."""
        # 1) Try local curated file first
        local_list = self._load_local_file()
        proxies: List[str] = list(local_list)

        sources = []
        if country:
            sources.append(
                f"https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=7000&country={country.lower()}&ssl=all&anonymity=all"
            )
        sources.extend(self._sources_default)
        # 2) Fetch remote public lists
        for src in sources:
            try:
                resp = requests.get(src, timeout=10)
                if resp.status_code != 200:
                    continue
                for line in resp.text.splitlines():
                    line = line.strip()
                    if not line or ":" not in line:
                        continue
                    host, port = line.split(":", 1)
                    if not port.isdigit():
                        continue
                    # Prefer typical HTTP/HTTPS ports
                    if port in self._allowed_ports:
                        proxies.append(f"{host}:{port}")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[ProxyProvider] Source failed {src}: {e}")
                continue

        random.shuffle(proxies)
        return proxies

    def get_proxy(self, country: Optional[str] = None) -> Optional[Dict[str, str]]:
        """Return a proxy dict suitable for requests/instaloader."""
        key = country.lower() if country else "global"
        if self._needs_refresh(key):
            self._cache[key] = self._fetch(country)
            self._cache_ts[key] = time.time()

        while self._cache.get(key):
            host_port = self._cache[key].pop()
            proxy = {"http": f"http://{host_port}", "https": f"http://{host_port}"}
            return proxy

        return None


proxy_provider = ProxyProvider()
