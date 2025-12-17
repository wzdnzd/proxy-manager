# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25


import base64
import math
import os
import random
import re
import threading
import time
import traceback
from collections import defaultdict
from concurrent import futures
from copy import deepcopy
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import yaml
from tqdm import tqdm

import settings
import subconverter
import utils
from cache import subscribe_cache as sc
from logger import logger
from subscribe import ConvertResult, SubscribeBase


class QuotedStr(str):
    pass


def quoted_scalar(dumper, data):  # pylint: disable=R0913
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')  # pylint: disable=R0913


class ProxyProcessor(object):
    """
    A singleton class to manage proxy processing operations
    with state tracking to prevent concurrent partition operations
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls, *args, **kwargs)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        """Initialize the processor state"""
        self._lock = threading.Lock()
        self._is_processing = False
        self._start_time = None
        self._end_time = None
        self._success = False
        self._error_message = None

    def is_processing(self) -> bool:
        """Check if a partition operation is currently in progress"""
        with self._lock:
            return self._is_processing

    def get_status(self) -> Dict:
        """Get the current status of the processor"""
        with self._lock:
            status = {
                "running": self._is_processing,
                "start_time": self._start_time.isoformat() if self._start_time else None,
                "duration": (
                    (datetime.now() - self._start_time).total_seconds()
                    if self._is_processing and self._start_time
                    else None
                ),
                "last_run_time": self._start_time.isoformat() if self._start_time else None,
                "last_run_duration": (
                    (self._end_time - self._start_time).total_seconds() if self._end_time and self._start_time else None
                ),
                "last_run_success": self._success if not self._is_processing else None,
                "error_message": self._error_message,
            }
            return status

    def split(self, content: str, max_size: int, prefix: str = "", suffix: str = "") -> Tuple[bool, str]:
        """
        Split and process proxies

        Args:
            content: The proxy content to process
            max_size: Maximum number of proxies per partition

        Returns:
            Tuple of (success, message)
        """
        # Check if already processing
        with self._lock:
            if self._is_processing:
                duration = (datetime.now() - self._start_time).total_seconds() if self._start_time else 0
                return False, f"A partition operation is already in progress and running for {duration:.1f} seconds"

            # Mark as processing and record start time
            self._is_processing = True
            self._start_time = datetime.now()
            self._error_message = None

        # Mark the beginning of a partition operation to prevent individual cache updates
        sc.start_partition_operation()

        try:
            if not content:
                self._set_completed(False, "Empty content provided")
                return False, "Empty content provided"

            # delete old subconverter config file
            subconverter_conf = os.path.join(subconverter.get_path(), "generate.ini")
            if os.path.exists(subconverter_conf) and os.path.isfile(subconverter_conf):
                os.remove(subconverter_conf)

            max_size = max(max_size, 1)
            prefix = utils.trim(prefix)
            suffix = utils.trim(suffix)

            nodes = decode(text=content, emoji=prefix == "")
            if not nodes:
                self._set_completed(False, "Failed to decode proxies")
                return False, "Failed to decode proxies"

            if settings.FILTER_CN:
                pattern = re.compile("中国|China|CN|🇨🇳", flags=re.I)
                nodes = [node for node in nodes if not re.search(pattern, node.get("name", ""))]

            policy = settings.CLOUDFLARE_POLICY
            proxies = nodes if policy == 0 else []

            if policy > 0:
                changed = False

                for proxy in nodes:
                    if re.search("cloudflare|google", proxy.get("name", ""), flags=re.I):
                        if policy == 1:
                            proxy["name"] = "美国"
                            changed = True
                        else:
                            continue

                    proxies.append(proxy)

                if changed:
                    records = defaultdict(list)
                    for proxy in proxies:
                        name = re.sub(r"-?(\d+|(\d+|\s+|(\d+)?-\d+)[A-Z])$", "", proxy.get("name", "")).strip()
                        proxy["name"] = name
                        records[name].append(proxy)

                    results = list()
                    for k, v in records.items():
                        if not k or not v:
                            continue

                        n = max(2, math.floor(math.log10(len(v))) + 1)
                        for index, node in enumerate(v):
                            node["name"] = f"{k} {str(index+1).zfill(n)}"
                            results.append(node)

                    # shuffle
                    for _ in range(3):
                        random.shuffle(results)

                    proxies = results

                total, remain = len(nodes), len(proxies)
                logger.info(
                    f"remove cloudflare nodes, policy: {policy}, total: {total}, remain: {remain}, deleted: {total - remain}"
                )

            # add prefix mark to name for each proxy
            if prefix:
                for proxy in proxies:
                    proxy["name"] = f"{prefix} {proxy.get('name', '')}"

            # add suffix mark to name for each proxy
            if suffix:
                for proxy in proxies:
                    proxy["name"] = f"{proxy.get('name', '')} {suffix}"

            # split proxies into multiple partitions
            partitions = []
            for i in range(0, len(proxies), max_size):
                part = proxies[i : i + max_size]
                index = i // max_size + 1
                partitions.append((part, index))

            # merge last partition with second-to-last if last partition size is <= max_size/3
            if len(partitions) >= 2 and len(partitions[-1][0]) <= max_size // 3:
                # remove last partition
                last, _ = partitions.pop()

                # remove second-to-last partition
                prev, cursor = partitions.pop()

                # merge the partitions
                merged = prev + last

                # add the merged partition back with the second-to-last index
                partitions.append((merged, cursor))

            # add expired warning to first partition
            if len(proxies) > 0 and settings.EXPIRED_WARNING:
                node = deepcopy(proxies[0])
                node["name"] = settings.EXPIRED_WARNING
                partitions.append(([node], 0))

            # execute convert
            tasks = [[p[0], p[1], t, w] for p in partitions for t in settings.SUPPORTED_TARGRTS for w in [True, False]]
            results = multi_thread_run(func=convert, tasks=tasks, show_progress=True, description="Convert")

            successed_tasks, failed_tasks = [], []
            for result in results:
                sb = SubscribeBase(
                    target=result.target,
                    partition=result.partition,
                    without_rules=result.without_rules,
                )
                if result.success:
                    successed_tasks.append(sb)
                else:
                    failed_tasks.append(sb)

            m, n, k = len(successed_tasks), len(failed_tasks), len(tasks)
            logger.info(f"convert finished, success: {m}, failed: {n}, total: {k}")

            if failed_tasks:
                logger.warning(f"failed tasks: {failed_tasks}")

            if m > 0:
                # remove old partitions greater than len(partitions)
                sc.clean_expired_partitions(partition=len(partitions) + 1)

                # Mark the end of the partition operation and refresh the cache
                sc.end_partition_operation(success=True)

                self._set_completed(True)
                return True, f"Successfully processed {m} out of {k} tasks"
            else:
                # Mark the end of the partition operation but don't refresh the cache
                sc.end_partition_operation(success=False)

                self._set_completed(False, "No tasks were successful")
                return False, "No tasks were successful"
        except Exception as e:
            error_msg = f"Error in split operation: {str(e)}"
            logger.error(error_msg)
            # Make sure to end the partition operation even if an exception occurs
            sc.end_partition_operation(success=False)

            self._set_completed(False, error_msg)
            return False, error_msg

    def _set_completed(self, success: bool, error_message: Optional[str] = None):
        """Mark the operation as completed and record the result"""
        with self._lock:
            self._is_processing = False
            self._end_time = datetime.now()
            self._success = success
            self._error_message = error_message


# Create a singleton instance
processor = ProxyProcessor()


def convert(proxies: List[Dict], partition: int, target: str, without_rules: bool) -> ConvertResult:
    """Convert proxies to target format"""
    result = ConvertResult(target=target, partition=partition, without_rules=without_rules)
    if not proxies or not isinstance(proxies, list):
        return result

    target = utils.trim(target)
    if target not in settings.SUPPORTED_TARGRTS:
        return result

    # save to file
    data = {"proxies": proxies}
    path = subconverter.get_path()
    source = utils.random_chars(length=8) + ".yaml"

    with open(os.path.join(path, source), "w+", encoding="utf8") as f:
        yaml.add_representer(QuotedStr, quoted_scalar)
        yaml.dump(data, f, allow_unicode=True)

    # random sleep
    time.sleep(random.random() * 3)

    # generate convert config
    artifact = f"{target}-{partition}-{str(without_rules).lower()}"
    extension = subconverter.get_extension(target=target)
    dest = f"{artifact}.{extension}"

    insert = settings.INSERT_URL and partition != 0
    success = subconverter.generate_conf(
        filepath=os.path.join(path, "generate.ini"),
        name=artifact,
        source=source,
        dest=dest,
        target=target,
        insert=insert,
        list_only=without_rules,
    )

    source_file = os.path.join(path, source)
    if not success:
        if os.path.exists(source_file) and os.path.isfile(source_file):
            os.remove(source_file)

        logger.error(
            f"cannot generate subconverter config file, target: {target}, index: {partition}, without_rules: {without_rules}"
        )
        return result

    # call subconverter to convert
    success = subconverter.convert(artifact=artifact)

    # delete source file
    if os.path.exists(source_file) and os.path.isfile(source_file):
        os.remove(source_file)

    if not success:
        logger.error(
            f"subconverter convert failed, target: {target}, index: {partition}, without_rules: {without_rules}"
        )
        return result

    # read dest file content and delete dest file
    content, filepath = "", os.path.join(path, dest)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf8", errors="ignore") as f:
            content = f.read()

        # delete dest file
        os.remove(filepath)

    if not content:
        logger.error(
            f"cannot get converted content, target: {target}, index: {partition}, without_rules: {without_rules}"
        )
        return result

    mixed = target == "v2ray" or target == "mixed" or "ss" in target
    if mixed and not utils.isb64encode(content=content):
        # base64 encode
        try:
            content = base64.b64encode(content.encode(encoding="UTF8")).decode(encoding="UTF8")
        except Exception:
            logger.error(f"base64 encode error, target: {target}, index: {partition}, without_rules: {without_rules}")
            return result

    # update database and cache (cache update will be skipped if partition operation is in progress)
    success = sc.update(target=target, content=content, without_rules=without_rules, partition=partition)
    result.success = success

    logger.info(
        f"convert completed, target: {target}, index: {partition}, without_rules: {without_rules}, success: {success}"
    )
    return result


def decode(text: str, artifact: str = "", emoji: bool = True) -> List[Dict]:
    text, nodes = utils.trim(text=text), []
    if not text:
        return []

    artifact = utils.trim(text=artifact)
    if not artifact:
        artifact = utils.random_chars(length=8)

    base_path = subconverter.get_path()
    v2ray_file = os.path.join(base_path, f"{artifact}.txt")
    clash_file = os.path.join(base_path, f"{artifact}.yaml")

    is_b64encode = utils.isb64encode(text)
    is_json = text.startswith("{") and text.endswith("}")

    # base64 encoding
    if not is_b64encode and not is_json and not re.search(r"^proxies:([\s\r\n]+)?$", text, flags=re.MULTILINE):
        text = base64.b64encode(text.encode(encoding="UTF8")).decode(encoding="UTF8")

    try:
        with open(v2ray_file, "w+", encoding="UTF8") as f:
            f.write(text)
            f.flush()
    except Exception:
        if os.path.exists(v2ray_file):
            os.remove(v2ray_file)

        logger.error(f"save file fialed, artifact: {artifact}")
        traceback.print_exc()

    generate_conf = os.path.join(base_path, "generate.ini")
    success = subconverter.generate_conf(generate_conf, artifact, f"{artifact}.txt", f"{artifact}.yaml", "clash", emoji)
    if not success:
        logger.error("cannot generate subconverter config file")
        os.remove(v2ray_file)
        return []

    time.sleep(random.random())
    success = subconverter.convert(artifact=artifact)
    logger.info(f"subconverter completed, artifact: [{artifact}]\tsuccess=[{success}]")

    os.remove(v2ray_file)
    if not success:
        return []

    with open(clash_file, "r", encoding="utf8", errors="ignore") as reader:
        config = None
        try:
            config = yaml.load(reader, Loader=yaml.SafeLoader)
        except yaml.constructor.ConstructorError:
            reader.seek(0, 0)
            yaml.add_multi_constructor(
                "str",
                lambda _loader, _suffix, node: str(node.value),
                Loader=yaml.SafeLoader,
            )
            config = yaml.load(reader, Loader=yaml.SafeLoader)
        except Exception:
            logger.error(f"cannot load yaml file, artifact: {artifact}, message:\n{traceback.format_exc()}")

        nodes = [] if not config else config.get("proxies", [])
    os.remove(clash_file)

    return [] if not nodes else nodes


def multi_thread_run(
    func: Callable,
    tasks: list,
    num_threads: int = None,
    show_progress: bool = False,
    description: str = "",
) -> list:
    if not func or not tasks or not isinstance(tasks, list):
        return []

    if num_threads is None or num_threads <= 0:
        num_threads = min(len(tasks), (os.cpu_count() or 1) * 3)

    funcname = getattr(func, "__name__", repr(func))

    results, starttime = [None] * len(tasks), time.time()
    with futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        if isinstance(tasks[0], (list, tuple)):
            collections = {executor.submit(func, *param): i for i, param in enumerate(tasks)}
        else:
            collections = {executor.submit(func, param): i for i, param in enumerate(tasks)}

        items = futures.as_completed(collections)
        if show_progress:
            description = utils.trim(description) or "Progress"
            items = tqdm(items, total=len(collections), desc=description, leave=True)

        for future in items:
            try:
                result = future.result()
                index = collections[future]
                results[index] = result
            except Exception as e:
                logger.error(f"function {funcname} execution generated an exception: {e}")

    logger.info(
        f"[Concurrent] multi-threaded execute [{funcname}] finished, count: {len(tasks)}, cost: {time.time()-starttime:.2f}s"
    )

    return results
