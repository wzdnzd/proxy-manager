# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import random
import re
import time
import traceback

import requests
import uvicorn
from flask import Flask, jsonify, request
from uvicorn.middleware.wsgi import WSGIMiddleware
from werkzeug.exceptions import HTTPException

import process
import setting
import utils
from cache import paste_cache
from logger import logger
from pastefy import client as pastefy

app = Flask(__name__)


@app.before_request
def intercept():
    if request.path == "/api/v1/partition":
        real = utils.trim(setting.WRITE_AUTHORIZATION_KEY)
        auth = utils.trim(request.headers.get("Authorization", "")).removeprefix("Bearer").strip()

        if real and real != auth:
            return jsonify({"success": False, "code": 401, "message": "auth failed"})


@app.route("/api/v1/partition", methods=["POST"])
def partition():
    link = utils.trim(setting.RAW_PROXIES_LINK)
    if not link or not re.match(r"https?://.*", link):
        return jsonify({"success": False, "code": 400, "message": "raw proxies link is required"})

    content, retry_count = "", 0
    while retry_count <= setting.MAX_RETRIES:
        try:
            response = requests.get(link, timeout=30)
            response.raise_for_status()

            try:
                content = response.content.decode("utf-8")
            except UnicodeDecodeError:
                content = response.content.decode("latin-1")
            break
        except requests.RequestException as e:
            retry_count += 1
            if retry_count <= setting.MAX_RETRIES:
                wait_time = min(2**retry_count + random.uniform(0, 1), setting.MAX_WAIT)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed after {setting.MAX_RETRIES} retries: {str(e)}")

    if not content:
        return jsonify({"success": False, "code": 503, "message": "fetch data failed"})

    try:
        result = process.split(content=content, max_size=setting.MAX_PROXIES_SIZE)
        paste_cache.refresh()
        return jsonify({"success": True, "code": 200, "message": "ok", "data": result})
    except:
        traceback.print_exc()
        logger.error("Failed to partition proxies")
        return jsonify({"success": False, "code": 503, "message": "partition failed"})


@app.route("/api/v1/subscribe/<token>", methods=["GET"])
def subscribe(token: str):
    token = utils.trim(token)
    if setting.READ_AUTHORIZATION_KEY and token != setting.READ_AUTHORIZATION_KEY:
        return jsonify({"success": False, "code": 401, "message": "auth failed"})

    target = utils.trim(request.args.get("target", ""))
    if not target:
        # extract target from User-Agent
        target = utils.extract_client(request.headers.get("User-Agent", ""))
    without_rules = utils.trim(request.args.get("list", "")).lower() in ["true", "1"]

    items = paste_cache.get(target=target, without_rules=without_rules)
    if not items:
        return jsonify({"success": False, "code": 404, "message": "no proxies to use"})

    paste_id = random.choice(items)
    try:
        content = pastefy.get_paste_content(paste_id=paste_id)
        if not content:
            return jsonify({"success": False, "code": 404, "message": "no proxies to use"})

        return content
    except:
        logger.error(f"Failed to get paste content: {paste_id}")
        return jsonify({"success": False, "code": 503, "message": "fetch data failed"})


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({"success": True, "code": 200, "message": "ok"})


@app.errorhandler(Exception)
def handle_exceptions(e: Exception):
    if isinstance(e, HTTPException):
        return jsonify({"success": False, "code": e.code, "message": e.description}), 200

    logger.error(f"{str(e)}")
    return jsonify({"success": False, "code": 503, "message": "internal server error"}), 503


if __name__ == "__main__":
    logger.info("start server...")
    app.run(host="0.0.0.0", port=8080)

    # Wrap the Flask app with WSGIMiddleware to make it compatible with Uvicorn (ASGI)
    # asgi_app = WSGIMiddleware(app)
    # uvicorn.run(asgi_app, host="0.0.0.0", port=8080)
