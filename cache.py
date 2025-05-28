# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import threading
import time
from collections import defaultdict
from typing import List, Optional

import settings
import utils
from dbclient import (
    create_table,
    delete_subscribe_expired,
    get_all_subscribe,
    get_subscribe,
    insert_subscribe,
)
from logger import logger
from subscribe import SubscribeDetail


class ReadWriteLock:
    """A lock object that allows many simultaneous "read" locks, but only one "write" lock.
    This implementation prioritizes readers over writers to ensure user requests are not blocked."""

    def __init__(self):
        self._lock = threading.RLock()  # Base lock for synchronizing access to lock state
        self._readers = 0  # Number of active readers
        self._writers = 0  # Number of active writers (0 or 1)
        self._write_waiting = 0  # Number of writers waiting
        self._reader_event = threading.Event()  # Event for readers to wait on
        self._writer_event = threading.Event()  # Event for writers to wait on
        self._reader_event.set()  # Initially allow readers
        self._writer_event.set()  # Initially allow writers
        self._timeout = 1  # Default timeout in seconds - shorter for faster response

    def acquire_read(self, timeout=None):
        """Acquire a read lock. Several threads can hold this type of lock.
        Readers are prioritized over writers.
        Returns True if the lock was acquired, False on timeout."""
        if timeout is None:
            timeout = self._timeout

        # Wait for reader event (blocked only if a writer is active)
        if not self._reader_event.wait(timeout=timeout):
            return False

        with self._lock:
            # Increment reader count
            self._readers += 1
            # If this is the first reader, block new writers
            if self._readers == 1:
                self._writer_event.clear()
            return True

    def release_read(self):
        """Release a read lock."""
        with self._lock:
            # Decrement reader count
            self._readers -= 1
            # If no more readers, allow a writer to proceed
            if self._readers == 0:
                self._writer_event.set()

    def acquire_write(self, timeout=None):
        """Acquire a write lock. Only one thread can hold this lock.
        Writers wait for all readers to finish.
        Returns True if the lock was acquired, False on timeout."""
        if timeout is None:
            timeout = self._timeout

        start_time = time.time()
        remaining_time = timeout

        with self._lock:
            # Increment waiting writers count
            self._write_waiting += 1

        try:
            # First wait for writer event (no active writers)
            if not self._writer_event.wait(timeout=remaining_time):
                return False

            # Update remaining time
            elapsed = time.time() - start_time
            remaining_time = max(0, timeout - elapsed)

            # Now acquire the writer event to block other writers
            with self._lock:
                if self._writers > 0:
                    # Another writer got it first
                    return False

                # Mark that we're now writing and block new readers
                self._writers = 1
                self._reader_event.clear()

            # Wait for all readers to finish
            # This is outside the lock to prevent deadlock
            current_readers = 0
            with self._lock:
                current_readers = self._readers

            if current_readers > 0:
                # Sleep and check periodically if readers are done
                check_interval = min(0.1, remaining_time)
                end_time = start_time + timeout

                while current_readers > 0 and time.time() < end_time:
                    time.sleep(check_interval)
                    with self._lock:
                        current_readers = self._readers

                if current_readers > 0:
                    # Readers didn't finish in time
                    with self._lock:
                        self._writers = 0
                        self._reader_event.set()
                    return False

            return True
        finally:
            with self._lock:
                # Decrement waiting writers count
                self._write_waiting -= 1

    def release_write(self):
        """Release a write lock."""
        with self._lock:
            # Mark that we're no longer writing
            self._writers = 0
            # Allow readers to proceed again
            self._reader_event.set()
            # Allow another writer to proceed
            self._writer_event.set()


class SubscribeCache(object):
    def __init__(self, table: str, refresh_interval: int = 3600):
        self._table = utils.trim(table)

        # Use Copy-on-Write pattern: maintain a reference to the current cache
        # and a lock only for switching this reference
        self._cache_ref = defaultdict(lambda: defaultdict(dict))
        self._switch_lock = threading.Lock()  # Lock only used when switching cache references

        self._last_update = 0
        self._refresh_interval = max(refresh_interval, 600)
        self._refresh_timer = None

        # Flag to indicate if a partition operation is in progress
        self._partition_in_progress = False
        self._partition_lock = threading.Lock()

        if not self._table:
            logger.error("Failed to initialize cache, table name cannot be empty")
            return

        # Create the table if it doesn't exist
        create_table(self._table)

        # Refresh the cache immediately on startup
        self.refresh()

        # Start the refresh timer
        self._start_refresh_timer()

    def __del__(self):
        """Destructor to cancel the refresh timer when the object is destroyed"""
        if self._refresh_timer:
            self._refresh_timer.cancel()

    def _get_rule_key(self, without_rules: bool) -> str:
        """Get the cache key for a specific rule setting"""
        return "without_rules" if without_rules else "with_rules"

    def _deep_copy_cache(self, cache):
        """Create a deep copy of the cache structure

        This is used for the Copy-on-Write pattern to create a new copy
        of the cache before modifying it.
        """
        new_cache = defaultdict(lambda: defaultdict(dict))
        for target, rules in cache.items():
            for rule_key, partitions in rules.items():
                for partition, content in partitions.items():
                    new_cache[target][rule_key][partition] = content
        return new_cache

    def _clean_target_cache_cow(self, cache, target: str, partition: int):
        """Clean cache items for a specific target with partition values greater than the threshold
        This version works on a specific cache object for Copy-on-Write pattern.

        Args:
            cache: The cache object to clean (not self._cache_ref)
            target: Target platform
            partition: Partition threshold, items with partition values greater than this will be deleted
        """
        # Iterate through all rule types (with_rules and without_rules)
        for element in list(cache[target].keys()):
            # Iterate through all partitions and delete those greater than the specified value
            for key in list(cache[target][element].keys()):
                try:
                    index = int(key)
                    if index > partition:
                        del cache[target][element][key]
                        logger.info(f"Cache item deleted: target={target}, rule_key={element}, partition={index}")
                except ValueError:
                    logger.warning(f"Invalid partition value in cache: {key}")

    def _clean_cache_items(self, partition: int, target: str = None):
        """Clean cache items with partition values greater than the specified threshold
        Note: This method should only be called with a write lock already acquired.

        Args:
            partition: Partition threshold, items with partition values greater than this will be deleted
            target: Target platform, if None, clean all platforms
        """
        if target:
            # If target is specified, only clean cache for that target
            target = utils.trim(target)
            if target in self._cache:
                self._clean_target_cache(target, partition)
        else:
            # If no target is specified, clean cache for all targets
            for key in list(self._cache.keys()):
                self._clean_target_cache(key, partition)

    def _clean_target_cache(self, target: str, partition: int):
        """Clean cache items for a specific target with partition values greater than the threshold
        Note: This method should only be called with a write lock already acquired.

        Args:
            target: Target platform
            partition: Partition threshold, items with partition values greater than this will be deleted
        """
        # Iterate through all rule types (with_rules and without_rules)
        for element in list(self._cache[target].keys()):
            # Iterate through all partitions and delete those greater than the specified value
            for key in list(self._cache[target][element].keys()):
                try:
                    index = int(key)
                    if index > partition:
                        del self._cache[target][element][key]
                        logger.info(f"Cache item deleted: target={target}, rule_key={element}, partition={index}")
                except ValueError:
                    logger.warning(f"Invalid partition value in cache: {key}")

    def _start_refresh_timer(self):
        """Start a timer to refresh the cache periodically"""
        if self._refresh_timer:
            self._refresh_timer.cancel()

        self._refresh_timer = threading.Timer(self._refresh_interval, self.refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def set_refresh_interval(self, interval: int):
        """Set the cache refresh interval in seconds"""
        if interval <= 0:
            logger.warning(f"Invalid refresh interval: {interval}, using default value: {self._refresh_interval}")
            return

        self._refresh_interval = interval
        logger.info(f"Cache refresh interval set to {interval} seconds")

        # Restart the timer with the new interval
        self._start_refresh_timer()

    def get(self, target: str, without_rules: bool = False, partition: int = 1) -> Optional[str]:
        """
        Get subscribe content from cache or database

        Args:
            target: Target platform (clash, v2ray, etc.)
            without_rules: Whether to get content without rules
            partition: Partition number

        Returns:
            Content string or None if not found
        """
        target = utils.trim(target)
        if not target:
            logger.error("Failed to get subscribe content, target cannot be empty")
            return None

        if partition < 0:
            logger.error("Failed to get subscribe content, partition must be greater than 0")
            return None

        rule_key = self._get_rule_key(without_rules)

        # Get the current cache reference - no lock needed for reading
        # This is the key benefit of Copy-on-Write: reads are completely lock-free
        current_cache = self._cache_ref

        # Try to get from cache first (completely lock-free)
        if (
            target in current_cache
            and rule_key in current_cache[target]
            and str(partition) in current_cache[target][rule_key]
        ):
            logger.info(f"Cache hit: target={target}, without_rules={without_rules}, partition={partition}")
            return current_cache[target][rule_key][str(partition)]

        # If not in cache, get from database
        logger.info(
            f"Cache miss: target={target}, without_rules={without_rules}, partition={partition}, fetching from database"
        )
        info = get_subscribe(self._table, target, without_rules, partition)
        if not info:
            logger.warning(
                f"Subscribe info not found in database: target={target}, without_rules={without_rules}, partition={partition}"
            )
            return None

        # Update the cache in a background thread to avoid blocking the response
        # Only if there's no partition operation in progress
        def update_cache_background():
            # Check if a partition operation is in progress
            with self._partition_lock:
                if self._partition_in_progress:
                    logger.info(f"Partition in progress, skipping individual cache update")
                    return

            # Create a new cache copy only for this small update
            with self._switch_lock:
                # Get the latest cache reference
                current_cache = self._cache_ref
                # Create a deep copy of the current cache
                new_cache = self._deep_copy_cache(current_cache)
                # Update the new cache
                new_cache[target][rule_key][str(partition)] = info.content
                # Switch the reference atomically
                self._cache_ref = new_cache
                self._last_update = int(time.time())

            logger.info(f"Cache updated for: target={target}, without_rules={without_rules}, partition={partition}")

        # Start a background thread to update the cache without blocking the response
        update_thread = threading.Thread(target=update_cache_background)
        update_thread.daemon = True
        update_thread.start()

        return info.content

    def update(self, target: str, content: str, without_rules: bool = False, partition: int = 1) -> bool:
        """
        Update subscribe content in cache and database

        Args:
            target: Target platform (clash, v2ray, etc.)
            content: Subscribe content
            without_rules: Whether the content is without rules
            partition: Partition number
        """
        target = utils.trim(target)
        if not target:
            logger.error("Failed to update subscribe content, target cannot be empty")
            return False

        if partition < 0:
            logger.error("Failed to update subscribe content, partition must be greater than 0")
            return False

        rule_key = self._get_rule_key(without_rules)

        # Check if a partition operation is in progress
        with self._partition_lock:
            partition_in_progress = self._partition_in_progress

        # If a partition operation is in progress, only update the database
        if partition_in_progress:
            logger.info(
                f"Partition in progress, skipping individual cache update for: target={target}, partition={partition}"
            )
            # Update database only
            success = insert_subscribe(
                self._table,
                SubscribeDetail(
                    target=target,
                    content=content,
                    without_rules=without_rules,
                    partition=partition,
                ),
            )
            return success

        # Update both cache and database
        # First update database to ensure data is persisted
        success = insert_subscribe(
            self._table,
            SubscribeDetail(
                target=target,
                content=content,
                without_rules=without_rules,
                partition=partition,
            ),
        )

        if not success:
            logger.error(
                f"Failed to update database: target={target}, without_rules={without_rules}, partition={partition}"
            )
            return False

        # Then update cache using Copy-on-Write
        with self._switch_lock:
            # Get the latest cache reference
            current_cache = self._cache_ref
            # Create a deep copy of the current cache
            new_cache = self._deep_copy_cache(current_cache)
            # Update the new cache
            new_cache[target][rule_key][str(partition)] = content
            # Switch the reference atomically
            self._cache_ref = new_cache
            self._last_update = int(time.time())

        logger.info(
            f"Cache and database updated: target={target}, without_rules={without_rules}, partition={partition}"
        )
        return True

    def clean_expired_partitions(self, partition: int, target: str = None) -> bool:
        """Delete subscribe info from cache and database where partition is greater than the specified value"""
        if partition < 0:
            logger.error("Failed to delete subscribe info, partition must be greater than 0")
            return False

        # First delete from database to ensure data is consistent
        try:
            if target:
                target = utils.trim(target)
                logger.info(f"Deleting all subscribe from database where target={target}, partition > {partition}")
                db_success = delete_subscribe_expired(self._table, partition, target)
            else:
                logger.info(f"Deleting all subscribe from database where partition > {partition}")
                db_success = delete_subscribe_expired(self._table, partition)

            if not db_success:
                logger.error(f"Failed to delete from database with partition > {partition}")
                return False
        except Exception as e:
            logger.error(f"Error deleting from database with partition > {partition}: {e}")
            return False

        # Then clean cache using Copy-on-Write
        with self._switch_lock:
            # Get the latest cache reference
            current_cache = self._cache_ref
            # Create a deep copy of the current cache
            new_cache = self._deep_copy_cache(current_cache)

            # Clean items in the new cache
            try:
                if target:
                    # If target is specified, only clean cache for that target
                    target = utils.trim(target)
                    if target in new_cache:
                        self._clean_target_cache_cow(new_cache, target, partition)
                else:
                    # If no target is specified, clean cache for all targets
                    for key in list(new_cache.keys()):
                        self._clean_target_cache_cow(new_cache, key, partition)

                # Switch the reference atomically
                self._cache_ref = new_cache
                self._last_update = int(time.time())
                logger.info(f"Cache cleaned for partition > {partition}")
                return True
            except Exception as e:
                logger.error(f"Error cleaning cache items with partition > {partition}: {e}")
                return False

    def get_all_partitions(self, target: str = None, without_rules: bool = None) -> List[int]:
        """
        Get all partitions for a target and rule setting

        Args:
            target: Target platform (clash, v2ray, etc.), if None, get all targets
            without_rules: Whether to get content without rules, if None, get both

        Returns:
            List of partition IDs
        """
        rule_key = self._get_rule_key(without_rules)

        # Get the current cache reference - no lock needed for reading
        current_cache = self._cache_ref

        # If we have specific target and rule setting, try to get from cache first (lock-free)
        if target and without_rules is not None:
            if target in current_cache and rule_key in current_cache[target]:
                # Get all partition IDs for this target and rule setting
                cache_partitions = [int(x) for x in current_cache[target][rule_key].keys() if x != '0']
                if cache_partitions:
                    logger.info(f"Cache hit for get_all_partitions: target={target}, without_rules={without_rules}")
                    return cache_partitions

        # If not in cache or we need all targets/rules, get from database
        infos = get_all_subscribe(self._table, target, without_rules)
        if not infos:
            logger.warning(f"No subscribe info found in database: target={target}, without_rules={without_rules}")
            return []

        # Collect partition IDs from database results
        result = [info.partition for info in infos if info.partition > 0]

        # Cache the results in a background thread to avoid blocking the response
        # Only if there's no partition operation in progress
        def update_cache_background():
            # Check if a partition operation is in progress
            with self._partition_lock:
                if self._partition_in_progress:
                    logger.info(f"Partition in progress, skipping cache update for get_all_partitions")
                    return

            # Create a new cache copy for this update
            with self._switch_lock:
                # Get the latest cache reference
                current_cache = self._cache_ref
                # Create a deep copy of the current cache
                new_cache = self._deep_copy_cache(current_cache)

                # Update the new cache with all the info
                for info in infos:
                    info_rule_key = self._get_rule_key(info.without_rules)
                    new_cache[info.target][info_rule_key][str(info.partition)] = info.content

                # Switch the reference atomically
                self._cache_ref = new_cache
                self._last_update = int(time.time())

            logger.info(f"Cache updated for get_all_partitions: target={target}, without_rules={without_rules}")

        # Start a background thread to update the cache
        update_thread = threading.Thread(target=update_cache_background)
        update_thread.daemon = True
        update_thread.start()

        return result

    def clear(self):
        """Clear the cache"""
        # Create an empty cache and switch atomically
        with self._switch_lock:
            self._cache_ref = defaultdict(lambda: defaultdict(dict))
            self._last_update = 0
            logger.info("Cache cleared")

    def refresh(self):
        """Refresh the cache with data from database"""
        logger.info("Refreshing cache...")

        try:
            # Get all subscribe info from database
            infos = get_all_subscribe(self._table, None, None)
            if not infos:
                logger.warning("No subscribe info found in database during refresh")
                return

            # Create a new empty cache
            new_cache = defaultdict(lambda: defaultdict(dict))

            # Fill the new cache with data from database
            for info in infos:
                rule_key = self._get_rule_key(info.without_rules)
                new_cache[info.target][rule_key][str(info.partition)] = info.content

            # Switch the reference atomically
            with self._switch_lock:
                self._cache_ref = new_cache
                self._last_update = int(time.time())
                logger.info(f"Cache refreshed with {len(infos)} items")
        except Exception as e:
            logger.error(f"Failed to refresh cache: {e}")
        finally:
            # Schedule the next refresh
            self._start_refresh_timer()

    def get_last_update(self) -> int:
        """Get the timestamp of the last cache update"""
        # This is a simple read of an integer which is atomic in Python, so no lock needed
        return self._last_update

    def start_partition_operation(self):
        """Mark the beginning of a partition operation

        This will set a flag to prevent individual cache updates during the partition operation.
        """
        with self._partition_lock:
            self._partition_in_progress = True
            logger.info(
                "Partition operation started - individual cache updates will be skipped, and cache will be refreshed"
            )

    def end_partition_operation(self, success: bool = True):
        """Mark the end of a partition operation

        If the operation was successful, refresh the cache from the database.
        """
        try:
            if success:
                # Refresh the cache from the database
                self.refresh()
                logger.info("Partition operation completed successfully - cache refreshed and cache will be refreshed")
            else:
                logger.warning("Partition operation failed - cache not refreshed")
        finally:
            # Always clear the flag even if refresh fails
            with self._partition_lock:
                self._partition_in_progress = False
                logger.info("Partition operation flag cleared - individual cache updates resumed")


subscribe_cache = SubscribeCache(table=settings.DB_TABLENAME, refresh_interval=settings.CACHE_REFRESH_INTERVAL)
