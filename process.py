# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25


import base64
import json
import os
import random
import re
import time
import traceback
from collections import defaultdict
from concurrent import futures
from dataclasses import dataclass
from typing import Callable, Dict, List

import yaml
from tqdm import tqdm

import setting
import subconverter
import utils
from logger import logger
from pastefy import client as pastefy

SUPPORTED_TARGRT = ["clash", "v2ray", "singbox", "loon", "surge", "quanx"]


class QuotedStr(str):
    pass


def quoted_scalar(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


@dataclass
class ConvertResult(object):
    # target: clash, v2ray, singbox, loon, surge, quanx
    target: str

    # title: paste filename
    title: str

    # paste_id: paste id
    paste_id: str

    # without_rules: whether to remove rules
    without_rules: bool


def split(content: str, max_size: int) -> Dict:
    if not content:
        return {}

    # delete old subconverter config file
    subconverter_conf = os.path.join(subconverter.get_path(), "generate.ini")
    if os.path.exists(subconverter_conf) and os.path.isfile(subconverter_conf):
        os.remove(subconverter_conf)

    max_size = max(max_size, 1)
    proxies = decode(text=content)
    if not proxies:
        return {}

    # split proxies into multiple partitions
    partitions = []
    for i in range(0, len(proxies), max_size):
        part = proxies[i : i + max_size]
        index = i // max_size + 1
        partitions.append((part, index))

    #  create folder with time as parent folder
    folder_name = time.strftime("%Y%m%d%H%M%S", time.localtime())
    parent = pastefy.create_folder(name=folder_name, parent=setting.PASTEFY_PUBLIC_FOLDER_ID)
    if not parent:
        logger.error("cannot create folder as parent folder for saving converted content")
        return {}

    # create folder for each target
    records = dict()
    for target in SUPPORTED_TARGRT:
        folder_id = pastefy.create_folder(name=target, parent=parent)
        if not folder_id:
            logger.warning(f"cannot create folder for saving converted content, target: {target}")
        else:
            records[target] = folder_id

    # execute convert
    tasks = [[p[0], p[1], t, w, f] for p in partitions for t, f in records.items() for w in [True, False]]
    items = multi_thread_run(func=convert, tasks=tasks, show_progress=True, description="Convert")

    result = {"folder_id": parent, "last_updated": int(time.time())}
    result["items"] = defaultdict(dict)
    flag = False

    for item in items:
        if not item or not isinstance(item, ConvertResult):
            continue

        flag = True
        key = "without_rules" if item.without_rules else "with_rules"
        result["items"][item.target][key][item.paste_id] = item.title

    if not flag:
        logger.warning(f"cannot convert any proxies, delete parent folder: {parent}")
        pastefy.delete_folder(parent)
        return {}

    old_parent_id = ""

    # get old parent folder id
    history = pastefy.get_paste_content(paste_id=setting.HISTORY_PASTE_ID)
    try:
        data = json.loads(history)
        if data and isinstance(data, dict):
            old_parent_id = data.get("folder_id", "")
    except:
        logger.error(f"cannot load history paste content, paste_id: {setting.HISTORY_PASTE_ID}")

    # update history paste
    text = json.dumps(result, indent=4, ensure_ascii=False)
    success = pastefy.update_paste(setting.HISTORY_PASTE_ID, content=text)
    logger.error(
        f"update history paste {"success" if success else "failed"}, paste_id: {setting.HISTORY_PASTE_ID}, content: {text}"
    )

    # delete old folder if update history paste successfully
    if success and old_parent_id:
        success = pastefy.delete_folder(old_parent_id)
        logger.info(f"delete old folder {'success' if success else 'failed'}, folder_id: {old_parent_id}")

    return result


def convert(proxies: List[Dict], index: int, target: str, without_rules: bool, folder_id: str) -> ConvertResult:
    if not proxies or not isinstance(proxies, list):
        return None

    target = utils.trim(target)
    if target not in SUPPORTED_TARGRT:
        return None

    folder_id = utils.trim(folder_id)
    if not folder_id:
        logger.error("folder_id is required for saving converted content")
        return None

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
    artifact = f"{target}-{index}-{str(without_rules).lower()}"
    extension = subconverter.get_extension(target=target)
    dest = f"{artifact}.{extension}"

    success = subconverter.generate_conf(
        filepath=os.path.join(path, "generate.ini"),
        name=artifact,
        source=source,
        dest=dest,
        target=target,
        list_only=without_rules,
    )
    if not success:
        if os.path.exists(os.path.join(path, source)):
            os.remove(os.path.join(path, source))

        logger.error(
            f"cannot generate subconverter config file, target: {target}, index: {index}, without_rules: {without_rules}"
        )
        return None

    # call subconverter to convert
    success = subconverter.convert(artifact=artifact)
    if not success:
        logger.error(f"subconverter convert failed, target: {target}, index: {index}, without_rules: {without_rules}")
        return None

    content, filepath = "", os.path.join(path, dest)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf8", errors="ignore") as f:
            content = f.read()

        os.remove(filepath)

    if not content:
        logger.error(f"cannot get converted content, target: {target}, index: {index}, without_rules: {without_rules}")
        return None

    # save to pastefy
    title = f"{'without-rules' if without_rules else 'with-rules'}-{index}.{extension}"
    pid = pastefy.create_paste(content=content, title=title, folder=folder_id)
    if not pid:
        logger.error(f"cannot create paste, target: {target}, index: {index}, without_rules: {without_rules}")
        return None

    return ConvertResult(target=target, title=title, paste_id=pid, without_rules=without_rules)


def decode(text: str, artifact: str = "") -> List[Dict]:
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
    except:
        if os.path.exists(v2ray_file):
            os.remove(v2ray_file)

        logger.error(f"save file fialed, artifact: {artifact}")
        traceback.print_exc()

    generate_conf = os.path.join(base_path, "generate.ini")
    success = subconverter.generate_conf(generate_conf, artifact, f"{artifact}.txt", f"{artifact}.yaml", "clash")
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
                lambda loader, suffix, node: str(node.value),
                Loader=yaml.SafeLoader,
            )
            config = yaml.load(reader, Loader=yaml.SafeLoader)
        except Exception as e:
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
