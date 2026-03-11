# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2026-03-11

import ipaddress
import json
import os
import threading
import time
from typing import Iterable, Optional

import requests

import settings
from logger import logger


def _resolve_cache_path(path: str, fallback_name: str) -> str:
    if path:
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(os.path.dirname(__file__), path))

    return os.path.abspath(os.path.join(os.path.dirname(__file__), fallback_name))


class GitHubMetaCache:
    def __init__(self):
        self._meta_url = settings.GITHUB_META_URL
        self._cache_path = _resolve_cache_path(settings.GITHUB_META_CACHE_FILE, "github-ip-ranges.json")
        self._refresh_interval = settings.GITHUB_META_REFRESH_INTERVAL
        self._timeout = settings.GITHUB_META_TIMEOUT

        self._lock = threading.Lock()
        self._last_refresh = 0
        self._last_failure = 0
        self._failure_cooldown = min(300, max(60, self._refresh_interval // 4))
        self._networks_v4 = []
        self._networks_v6 = []
        self._host_patterns = []
        self._loaded = False

        # Load from disk on startup for faster availability
        self._load_from_disk()

    def _load_from_disk(self, allow_refresh: bool = True) -> bool:
        if not os.path.exists(self._cache_path) or not os.path.isfile(self._cache_path):
            if allow_refresh:
                logger.error(f"Cache file: {self._cache_path} not found, load it from remote")
            else:
                logger.error(f"Cache file: {self._cache_path} not found, skip load it")

            return self._refresh(force=True) if allow_refresh else False

        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._build_indexes(data)
            try:
                self._last_refresh = int(os.path.getmtime(self._cache_path))
            except Exception:
                self._last_refresh = int(time.time())
            self._loaded = True

            logger.info(f"Loaded GitHub meta cache from {self._cache_path}")
            return True
        except Exception as exc:
            logger.warning(f"Failed to load GitHub meta cache from {self._cache_path}: {exc}")
            return self._refresh(force=True) if allow_refresh else False

    def _write_cache(self, data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            tmp_path = f"{self._cache_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True)
            os.replace(tmp_path, self._cache_path)
        except Exception as exc:
            logger.warning(f"Failed to write GitHub meta cache: {exc}")

    def _fetch_remote(self) -> Optional[dict]:
        if not self._meta_url:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Accept": "application/vnd.github+json",
        }

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(self._meta_url, timeout=self._timeout, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                if attempt >= max_attempts:
                    logger.warning(f"Failed to fetch GitHub meta after {max_attempts} attempts: {exc}")
                    return None

                backoff = min(2 ** (attempt - 1), 10)
                logger.warning(
                    f"Fetch GitHub meta failed (attempt {attempt}/{max_attempts}): {exc}. Retry in {backoff}s"
                )
                time.sleep(backoff)

        return None

    def _build_indexes(self, data: dict) -> None:
        networks_v4 = []
        networks_v6 = []
        host_patterns = []

        for key in ["actions", "actions_macos"]:
            for cidr in data.get(key, []) or []:
                try:
                    network = ipaddress.ip_network(cidr, strict=False)
                    if network.version == 4:
                        networks_v4.append(network)
                    else:
                        networks_v6.append(network)
                except Exception:
                    continue

        domains = data.get("domains", {}) or {}
        for pattern in domains.get("actions", []) or []:
            pattern = str(pattern).strip().lower()
            if pattern:
                host_patterns.append(pattern)

        self._networks_v4 = networks_v4
        self._networks_v6 = networks_v6
        self._host_patterns = host_patterns

        logger.info(
            f"GitHub meta cache loaded: IPv4={len(self._networks_v4)}, IPv6={len(self._networks_v6)}, "
            f"host={len(self._host_patterns)}"
        )

    def _refresh(self, force: bool = False) -> bool:
        now = int(time.time())
        if self._should_skip_refresh(now, force):
            return False

        with self._lock:
            now = int(time.time())
            if self._should_skip_refresh(now, force):
                return False

            data = self._fetch_remote()
            if data:
                self._build_indexes(data)
                self._write_cache(data)
                self._last_refresh = int(time.time())
                self._last_failure = 0
                self._loaded = True
                return True

            self._last_failure = int(time.time())
            if not self._loaded and self._load_from_disk(allow_refresh=False):
                logger.warning("Using stale GitHub meta cache due to refresh failure")
                return True

        return False

    def _should_skip_refresh(self, now: int, force: bool) -> bool:
        if force:
            return False
        if self._loaded and now - self._last_refresh < self._refresh_interval:
            elapsed = float(now - self._last_refresh)
            remaining = float(self._refresh_interval) - elapsed
            logger.debug(
                "Skip GitHub meta refresh: last refresh %.1fs ago, next allowed in %.1fs",
                elapsed,
                max(0.0, remaining),
            )
            return True
        if self._last_failure and now - self._last_failure < self._failure_cooldown:
            elapsed = float(now - self._last_failure)
            remaining = float(self._failure_cooldown) - elapsed
            logger.warning(
                "Skip GitHub meta refresh: last failure %.1fs ago, cooldown remaining %.1fs",
                elapsed,
                max(0.0, remaining),
            )
            return True
        return False

    def _ip_in_networks(self, ip: ipaddress._BaseAddress, networks: Iterable[ipaddress._BaseNetwork]) -> bool:
        return any(ip in network for network in networks)

    def _host_matches(self, host: str) -> bool:
        if not host:
            return False

        host = host.strip().lower().strip(".")
        if not host:
            return False

        for pattern in self._host_patterns:
            if not pattern:
                continue
            if "*" in pattern:
                if pattern.startswith("*."):
                    suffix = pattern[2:]
                    if host == suffix or host.endswith("." + suffix):
                        return True
                else:
                    # Fallback for rare wildcard patterns
                    try:
                        import fnmatch

                        if fnmatch.fnmatch(host, pattern):
                            return True
                    except Exception:
                        continue
            else:
                if host == pattern:
                    return True
        return False

    def block(self, ip: str = "", host: str = "") -> bool:
        self._refresh()

        if ip:
            try:
                obj = ipaddress.ip_address(ip)
                networks = self._networks_v4 if obj.version == 4 else self._networks_v6
                if self._ip_in_networks(obj, networks):
                    return True
            except Exception:
                pass

        if host and self._host_matches(host):
            return True

        return False


client = GitHubMetaCache()
