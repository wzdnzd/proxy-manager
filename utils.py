# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25


import os
import platform
import random
import re
import string
import subprocess
import sys

from logger import logger


def trim(text: str) -> str:
    if not text or type(text) != str:
        return ""

    return text.strip()


def is_number(num: str) -> bool:
    try:
        float(num)
        return True
    except ValueError:
        return False


def cmd(command: list, output: bool = False) -> tuple[bool, str]:
    if command is None or len(command) == 0:
        return False, ""

    p = (
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if output
        else subprocess.Popen(command)
    )
    p.wait()

    success, content = p.returncode == 0, ""
    if output:
        try:
            content = p.stdout.read().decode("utf8")
        except:
            content = ""
    return success, content


def chmod(binfile: str) -> None:
    if not os.path.exists(binfile) or os.path.isdir(binfile):
        raise ValueError(f"cannot found bin file: {binfile}")

    operating_system = str(platform.platform())
    if operating_system.startswith("Windows"):
        return
    elif operating_system.startswith("macOS") or operating_system.startswith("Linux"):
        cmd(["chmod", "+x", binfile])
    else:
        logger.error("Unsupported Platform")
        sys.exit(0)


def extract_client(text: str) -> str:
    content = trim(text)

    if content:
        if re.search(r"clash|mihomo", content, flags=re.I):
            return "clash"
        elif re.search("singbox", content, flags=re.I):
            return "singbox"
        elif re.search(r"quan(ult)?x?", content, flags=re.I):
            return "quanx"
        elif re.search(r"surge", content, flags=re.I):
            return "surge"
        elif re.search(r"loon", content, flags=re.I):
            return "loon"

    return "v2ray"


def isb64encode(content: str, padding: bool = True) -> bool:
    if not content:
        return False

    regex = "^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{4}|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)$"
    b64flag = re.match(regex, content)
    if not b64flag and len(content) % 4 != 0 and padding:
        content += "=" * (4 - len(content) % 4)
        b64flag = re.match(regex, content)

    return b64flag is not None


def random_chars(length: int = 8) -> str:
    return "".join(random.sample(string.ascii_letters + string.digits, max(length, 1)))


def write_file(filename: str, lines: list) -> bool:
    if not filename or not lines:
        logger.error(f"filename or lines is empty, filename: {filename}")
        return False

    try:
        if not isinstance(lines, str):
            lines = "\n".join(lines)

        filepath = os.path.abspath(os.path.dirname(filename))
        os.makedirs(filepath, exist_ok=True)
        with open(filename, "w+", encoding="UTF8") as f:
            f.write(lines)
            f.flush()

        return True
    except:
        return False
