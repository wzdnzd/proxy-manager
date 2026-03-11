# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import os

import pymysql

import utils

"""
Configuration settings for the application
"""

# The maximum number of retries for failed requests
MAX_RETRIES: int = max(int(os.environ.get("MAX_RETRIES", 3)), 1)

# The maximum wait time in seconds for retries
MAX_WAIT: int = max(int(os.environ.get("MAX_WAIT", 10)), 1)

# The maximum number of proxies per paste
MAX_PROXIES_SIZE = max(int(os.environ.get("MAX_PROXIES_SIZE", 150)), 10)

# The link for raw proxies. Must be set and cannot be empty
RAW_PROXIES_LINK: str = utils.trim(os.environ.get("RAW_PROXIES_LINK", ""))

# Supported targets
SUPPORTED_TARGRTS: set = utils.parse_supported_targets(os.environ.get("SUPPORTED_TARGRTS", ""))

# Auth key for write API
WRITE_AUTHORIZATION_KEY: str = utils.trim(os.environ.get("WRITE_AUTHORIZATION_KEY", ""))

# Auth key for read API
READ_AUTHORIZATION_KEY: str = utils.trim(os.environ.get("READ_AUTHORIZATION_KEY", ""))

# Cache refresh interval in seconds
CACHE_REFRESH_INTERVAL: int = max(int(os.environ.get("CACHE_REFRESH_INTERVAL", 3600)), 600)

# Server port for the API
SERVER_PORT: int = int(os.environ.get("SERVER_PORT", 7860))

# Prefix mark for shared proxies
ADDITIONAL_PREFIX: str = utils.trim(os.environ.get("ADDITIONAL_PREFIX", ""))

# Suffix mark for shared proxies
ADDITIONAL_SUFFIX: str = utils.trim(os.environ.get("ADDITIONAL_SUFFIX", ""))

# Cloudflare proxy processing policy, 0 means no processing, 1 means rename to US, 2 means discard
CLOUDFLARE_POLICY: int = int(os.environ.get("CLOUDFLARE_POLICY", 0))

# Database server address
DB_HOST = utils.trim(os.environ.get("DB_HOST", "127.0.0.1"))

# Database server port
DB_PORT = int(os.environ.get("DB_PORT", 3306))

# Database username
DB_USERNAME = utils.trim(os.environ.get("DB_USERNAME", "root"))

# Database password
DB_PASSWORD = utils.trim(os.environ.get("DB_PASSWORD", ""))

# Database name
DB_DATABASE = utils.trim(os.environ.get("DB_DATABASE", "proxies"))

# Database table name
DB_TABLENAME = utils.trim(os.environ.get("DB_TABLENAME", "public"))

# Database connection charset
DB_CHARSET = "utf8mb4"

# Number of idle connections to create at startup (default 0 means no connections are created at start)
DB_MIN_CACHED = 1

# Maximum number of idle connections in the pool (default 0 means unlimited pool size)
DB_MAX_CACHED = 0

# Maximum number of shared connections (default 0 means all connections are dedicated). If the maximum is reached, requested shared connections will be shared
DB_MAX_SHARED = 10

# Maximum number of connections to create in the pool (default 0 means unlimited)
DB_MAX_CONNECYIONS = 300

# Behavior when the pool has reached its maximum size (default 0 or False means return an error)
DB_BLOCKING = True

# Maximum number of times a single connection can be reused (default 0 or False means unlimited reuse). When the maximum is reached, the connection will be automatically reset (closed and reopened)
DB_MAX_USAGE = 0

# An optional list of SQL commands to prepare each session
DB_SET_SESSION = None

# Module used to connect to the database
DB_CREATOR = pymysql

# Forward if token is error
REDIRECT_URL = utils.trim(os.getenv("REDIRECT_URL", ""))

# Insert default node if true
INSERT_URL = utils.trim(os.getenv("INSERT_URL", "")).lower() in ["1", "true"]

# Filter Chinese proxies
FILTER_CN = utils.trim(os.getenv("FILTER_CN", "")).lower() in ["1", "true"]

# Expire warning
EXPIRED_WARNING = utils.trim(os.getenv("EXPIRED_WARNING", ""))

# Thread number for partition
PARTITION_THREAD_NUM = int(os.environ.get("PARTITION_THREAD_NUM", -1))

# Add Github server's IP to blacklist if true
BAN_GITHUB_IP = utils.trim(os.getenv("BAN_GITHUB_IP", "")).lower() in ["1", "true"]

# GitHub meta API for actions IP ranges
GITHUB_META_URL = utils.trim(os.getenv("GITHUB_META_URL", "https://api.github.com/meta"))

# GitHub meta cache file path (relative paths are resolved against project root)
GITHUB_META_CACHE_FILE = utils.trim(os.getenv("GITHUB_META_CACHE_FILE", "github-ip-ranges.json"))

# GitHub meta refresh interval (seconds)
GITHUB_META_REFRESH_INTERVAL = max(int(os.getenv("GITHUB_META_REFRESH_INTERVAL", 86400)), 600)

# GitHub meta request timeout (seconds)
GITHUB_META_TIMEOUT = max(int(os.getenv("GITHUB_META_TIMEOUT", 60)), 1)
