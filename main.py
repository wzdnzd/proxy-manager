# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import concurrent
import random
import re
import sys
import time

import requests
import uvicorn
from flask import Flask, jsonify, redirect, request
from uvicorn.middleware.wsgi import WSGIMiddleware
from werkzeug.exceptions import HTTPException

import settings
import utils
from cache import subscribe_cache as sc
from logger import logger
from process import processor

app = Flask(__name__)


@app.before_request
def intercept():
    if request.path.startswith("/api/v1/partition"):
        real = utils.trim(settings.WRITE_AUTHORIZATION_KEY)
        auth = utils.trim(request.headers.get("Authorization", "")).removeprefix("Bearer").strip()

        if real and real != auth:
            return jsonify({"success": False, "code": 401, "message": "Auth failed"})


@app.route("/api/v1/partition/submit", methods=["POST"])
def partition():
    # Check if a partition operation is already in progress
    if processor.is_processing():
        status = processor.get_status()
        duration = status.get("duration", 0)
        message = f"A partition operation is already in progress and running for {duration:.1f} seconds"

        logger.info(message)
        return jsonify({"success": False, "code": 409, "message": message})

    link = utils.trim(settings.RAW_PROXIES_LINK)
    if not link or not re.match(r"https?://.*", link):
        return jsonify({"success": False, "code": 400, "message": "Raw proxies link is required"})

    content, retry_count = "", 0
    while retry_count <= settings.MAX_RETRIES:
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
            if retry_count <= settings.MAX_RETRIES:
                wait_time = min(2**retry_count + random.uniform(0, 1), settings.MAX_WAIT)
                logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed after {settings.MAX_RETRIES} retries: {str(e)}")

    if not content:
        return jsonify({"success": False, "code": 503, "message": "Fetch data failed"})

    try:
        # Create a background thread to process the data without waiting for completion
        thread = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = thread.submit(
            processor.split,
            content=content,
            max_size=settings.MAX_PROXIES_SIZE,
            prefix=settings.ADDITIONAL_PREFIX,
            suffix=settings.ADDITIONAL_SUFFIX,
        )

        # Add a callback to shutdown the executor when the task is done
        def done_callback(future):
            try:
                # Check if there was an exception
                if future.exception():
                    logger.error(f"Background task failed: {future.exception()}")
                else:
                    success, message = future.result()
                    logger.info(f"Background task completed: success={success}, message={message}")
            finally:
                # Shutdown the executor
                thread.shutdown(wait=False)

        future.add_done_callback(done_callback)

        # Return success immediately without waiting for the thread to complete
        return jsonify({"success": True, "code": 200, "message": "Partition operation started"})
    except Exception as e:
        error_msg = f"Failed to start partition operation: {str(e)}"
        logger.error(error_msg)
        return jsonify({"success": False, "code": 503, "message": error_msg})


@app.route("/api/v1/subscribe", methods=["GET"])
def subscribe():
    token = utils.trim(request.args.get("token", ""))
    expired = False

    if settings.READ_AUTHORIZATION_KEY and token != settings.READ_AUTHORIZATION_KEY:
        if settings.EXPIRED_WARNING:
            expired = True
        elif settings.REDIRECT_URL:
            return redirect(location=settings.REDIRECT_URL)
        else:
            return jsonify({"success": False, "code": 401, "message": "Token is invalid"})

    target = utils.trim(request.args.get("target", "")).lower()
    if not target:
        # extract target from User-Agent
        target = utils.extract_client(request.headers.get("User-Agent", ""))

    if target not in settings.SUPPORTED_TARGRTS:
        if target == "v2ray" and "mixed" in settings.SUPPORTED_TARGRTS:
            target = "mixed"
        elif target == "mixed" and "v2ray" in settings.SUPPORTED_TARGRTS:
            target = "v2ray"
        else:
            if settings.REDIRECT_URL:
                return redirect(location=settings.REDIRECT_URL)

            return jsonify({"success": False, "code": 400, "message": f"Target {target} is not supported"})

    without_rules = utils.trim(request.args.get("list", "")).lower() in ["true", "1"]

    partition = None
    if expired:
        partition = 0
    else:
        if request.args.get("partition", None):
            try:
                partition = int(request.args.get("partition"))
            except Exception:
                pass

        if not partition:
            ids = sc.get_all_partitions(target=target, without_rules=without_rules)
            if not ids:
                return jsonify({"success": False, "code": 404, "message": "No proxies to use"})

            partition = random.choice(ids)

    content = sc.get(target=target, without_rules=without_rules, partition=partition)
    if not content:
        return jsonify({"success": False, "code": 404, "message": "No proxies to use"})

    if expired:
        timestamp, total = int(time.time()), 214748364800
        upload, download = 106374182400, 109374182400
    else:
        timestamp, total = 4102413803, sys.maxsize
        upload, download = random.randint(0, int(1e11)), random.randint(0, int(1e11))

    userinfo = f"upload={upload}; download={download}; total={total}; expire={timestamp}"

    return content, 200, {"Content-Type": "text/plain; charset=utf-8", "Subscription-Userinfo": userinfo}


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({"success": True, "code": 200, "message": "OK"})


@app.route("/api/v1/partition/status", methods=["GET"])
def state():
    """Get the status of the current or last partition operation"""
    status = processor.get_status()

    # Format the response
    data = {"success": True, "code": 200, "data": status}

    # If there's an error message and no operation is in progress, consider it a partial failure
    if status.get("error_message") and not status.get("running"):
        data["success"] = False
        data["message"] = status.get("error_message")

    return jsonify(data)


@app.errorhandler(Exception)
def handle_exceptions(e: Exception):
    if isinstance(e, HTTPException):
        return jsonify({"success": False, "code": e.code, "message": e.description}), 200

    logger.error(f"{str(e)}")
    return jsonify({"success": False, "code": 503, "message": "Internal server error"}), 503


if __name__ == "__main__":
    logger.info(f"Start server, listen port: {settings.SERVER_PORT}...")

    # Wrap the Flask app with WSGIMiddleware to make it compatible with Uvicorn (ASGI)
    asgi_app = WSGIMiddleware(app)
    uvicorn.run(asgi_app, host="0.0.0.0", port=settings.SERVER_PORT)
