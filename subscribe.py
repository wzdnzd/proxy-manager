# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

from dataclasses import dataclass


@dataclass
class SubscribeBase(object):
    # target: clash, v2ray, singbox, loon, surge, quanx
    target: str

    # without_rules: whether to remove rules
    without_rules: bool

    # partition: partition number
    partition: int


@dataclass
class SubscribeDetail(SubscribeBase):
    # content: subscribe content
    content: str

    # created_at: created time (unix timestamp)
    created_at: int = None

    # updated_at: updated time (unix timestamp)
    updated_at: int = None


@dataclass
class ConvertResult(SubscribeBase):
    # true: success, false: failed
    success: bool = False
