# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import json
import threading
import time
from collections import defaultdict
from typing import Dict, List

import setting
import utils
from logger import logger
from pastefy import client as pastefy


class PasteCache:
    """
    Cache system for storing paste ID lists of different types, including versions with and without rules.
    Supports various types such as clash, singbox, v2ray, etc.
    """

    def __init__(self, paste_id: str, refresh_interval: int = 3600):
        """
        Initialize the cache system with paste_id

        Args:
            paste_id: ID of the paste to load cache data from
            refresh_interval: Interval in seconds for automatic cache refresh (default: 3600 seconds = 1 hour)
        """
        paste_id = utils.trim(paste_id)
        if not paste_id:
            raise ValueError("paste_id is required")

        self._paste_id = paste_id
        self._cache: Dict[str, Dict[str, List[str]]] = defaultdict(dict)
        self._folder_id: str = ""
        self._last_updated: int = -1

        self._refresh_interval = max(60, refresh_interval)  # Minimum interval is 60 seconds
        self._timer = None
        self._stop_event = threading.Event()

        # Initial refresh
        self.refresh()

        # Start automatic refresh
        self.start_auto_refresh()

    def __del__(self):
        """
        Destructor to ensure timer is stopped when object is destroyed
        """
        try:
            self.stop_auto_refresh()
        except:
            pass

    def refresh(self) -> None:
        """
        Refresh cache data from paste with paste_id

        Returns:
            None
        """
        try:
            content = pastefy.get_paste_content(paste_id=self._paste_id)
            if not content:
                return

            data = json.loads(content)
            if not data or not isinstance(data, dict):
                logger.error(f"Failed to load cache data from paste: {self._paste_id} due to invalid data format")
                return

            items = data.get("items", {})
            if items and not isinstance(items, dict):
                logger.error(f"Failed to load cache data from paste: {self._paste_id} due to invalid data format")
                return

            result = defaultdict(dict)
            for target, item in items.items():
                if not item or not isinstance(item, dict):
                    continue

                for k, v in item.items():
                    if not v or not isinstance(v, dict):
                        continue

                    paste_ids = list(v.keys())
                    result[target][k] = paste_ids

            self._cache = result or {}
            self._folder_id = data.get("folder_id", "")
            self._last_updated = data.get("last_updated", int(time.time()))
        except:
            logger.error(f"Failed to load cache data from paste: {self._paste_id}")

    def start_auto_refresh(self) -> None:
        """
        Start automatic refresh of cache data at specified intervals

        Returns:
            None
        """
        if self._timer is not None:
            return  # Timer already running

        self._stop_event.clear()
        self._schedule_next_refresh()
        logger.info(f"Automatic cache refresh started with interval of {self._refresh_interval} seconds")

    def _schedule_next_refresh(self) -> None:
        """
        Schedule the next refresh if not stopped

        Returns:
            None
        """
        if not self._stop_event.is_set():
            self._timer = threading.Timer(self._refresh_interval, self._auto_refresh_task)
            self._timer.daemon = True  # Allow the program to exit even if the timer is still running
            self._timer.start()

    def _auto_refresh_task(self) -> None:
        """
        Task to be executed by the timer for automatic refresh

        Returns:
            None
        """
        try:
            logger.info("Performing automatic cache refresh")
            self.refresh()
        except Exception as e:
            logger.error(f"Error during automatic cache refresh: {e}")
        finally:
            self._schedule_next_refresh()  # Schedule next refresh regardless of success/failure

    def stop_auto_refresh(self) -> None:
        """
        Stop automatic refresh of cache data

        Returns:
            None
        """
        self._stop_event.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("Automatic cache refresh stopped")

    def set_refresh_interval(self, interval: int) -> None:
        """
        Set the refresh interval

        Args:
            interval: New interval in seconds for automatic cache refresh

        Returns:
            None
        """
        old_interval = self._refresh_interval
        self._refresh_interval = max(60, interval)  # Minimum interval is 60 seconds

        if self._refresh_interval != old_interval:
            logger.info(f"Refresh interval changed from {old_interval} to {self._refresh_interval} seconds")

            # Restart the timer with the new interval if it's running
            if self._timer is not None:
                self.stop_auto_refresh()
                self.start_auto_refresh()

    def get(self, target: str, without_rules: bool = False) -> List[str]:
        """
        Get paste IDs for a specific target and without_rules

        Args:
            target: Target type
            without_rules: Whether to get paste IDs without rules

        Returns:
            List[str]: List of paste IDs
        """
        target = utils.trim(target).lower()
        if not target:
            return []

        item = self._cache.get(target, {})
        if not item:
            return []

        key = "without_rules" if without_rules else "with_rules"
        return item.get(key, [])


paste_cache = PasteCache(setting.HISTORY_PASTE_ID, refresh_interval=max(setting.CACHE_REFRESH_INTERVAL, 600))
