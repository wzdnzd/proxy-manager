# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import os

import utils

"""
Configuration settings for the application
"""

# The base URL for the Pastefy API
BASE_URL: str = "https://pastefy.app"

# The API key for authentication with the Pastefy API. Must be set and cannot be empty
PASTEFY_API_KEY: str = utils.trim(os.environ.get("PASTEFY_API_KEY", ""))

# The maximum number of retries for failed requests
MAX_RETRIES: int = max(int(os.environ.get("MAX_RETRIES", 3)), 1)

# The maximum wait time in seconds for retries
MAX_WAIT: int = max(int(os.environ.get("MAX_WAIT", 10)), 1)

# The maximum number of proxies per paste
MAX_PROXIES_SIZE = max(int(os.environ.get("MAX_PROXIES_SIZE", 150)), 10)

# The ID of the folder for public pastes. Must be set and cannot be empty
PASTEFY_PUBLIC_FOLDER_ID: str = utils.trim(os.environ.get("PASTEFY_PUBLIC_FOLDER_ID", ""))

# The ID of the paste for history. Must be set and cannot be empty
HISTORY_PASTE_ID: str = utils.trim(os.environ.get("HISTORY_PASTE_ID", ""))

# The link for raw proxies. Must be set and cannot be empty
RAW_PROXIES_LINK: str = utils.trim(os.environ.get("RAW_PROXIES_LINK", ""))

# Auth key for write API
WRITE_AUTHORIZATION_KEY: str = utils.trim(os.environ.get("WRITE_AUTHORIZATION_KEY", ""))

# Auth key for read API
READ_AUTHORIZATION_KEY: str = utils.trim(os.environ.get("READ_AUTHORIZATION_KEY", ""))

# The interval in seconds for automatic cache refresh (default: 3600 seconds = 1 hour)
CACHE_REFRESH_INTERVAL: int = max(int(os.environ.get("CACHE_REFRESH_INTERVAL", 3600)), 600)
