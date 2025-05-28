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

# Water mark for shared proxies
WATER_MARK: str = utils.trim(os.environ.get("WATER_MARK", ""))

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
