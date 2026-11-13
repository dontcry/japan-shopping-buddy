# -*- coding: utf-8 -*-
"""日淘搭子 · 公共工具库

凭证统一从环境变量读取，杜绝硬编码；HTTP 走 urllib（无第三方依赖）。

凭证优先级（从高到低）：
1. 环境变量（RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY / PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET）
2. JSB_SECRETS 指向的 JSON 文件路径
3. 自动发现的 secrets.json（脚本同级 → Skill 根目录 → 上级 2 层）

代理：JSB_PROXY=1 启用（默认 0=不启用，云端服务器直连即可；本地开发需显式设 1）。
"""
import base64
import json
import os
import ssl
import urllib.error
import urllib.request

DEFAULT_PROXY = "http://127.0.0.1:7890"


class JsbError(Exception):
    """业务/可预期错误：向上打印友好提示，不抛裸异常栈。"""


def _find_secrets_json():
    """按候选路径依次尝试找 secrets.json，返回第一个存在的。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "secrets.json"),                       # scripts/secrets.json
        os.path.join(here, "..", "secrets.json"),                 # Skill 根/secrets.json
        os.path.join(here, "..", "..", "secrets.json"),           # 上级 2 层
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def load_secrets():
    """返回凭证字典，键为大写环境变量名。"""
    keys = [
        "RAKUTEN_APPLICATION_ID",
        "RAKUTEN_ACCESS_KEY",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
    ]
    secrets = {k: os.environ.get(k) for k in keys}

    # 候选 JSON 文件：显式 JSB_SECRETS > 自动发现
    json_paths = []
    explicit = os.environ.get("JSB_SECRETS")
    if explicit and os.path.isfile(explicit):
        json_paths.append(explicit)
    auto = _find_secrets_json()
    if auto:
        json_paths.append(auto)

    for path in json_paths:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if isinstance(v, str) and v and not secrets.get(k):
                secrets[k] = v

    return secrets


def proxy_enabled():
    """云端默认直连（"0"），本地开发需显式 JSB_PROXY=1 启用代理。"""
    return os.environ.get("JSB_PROXY", "0").strip().lower() not in ("0", "off", "false", "no")


def _opener(use_proxy):
    handlers = []
    if use_proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": DEFAULT_PROXY, "https": DEFAULT_PROXY})
        )
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    ctx = ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def http_request(method, url, headers=None, body=None, use_proxy=None, timeout=15):
    """返回 (status_code, text)。可预期的 HTTP 错误也返回 status+body，供上层解析。"""
    if use_proxy is None:
        use_proxy = proxy_enabled()
    payload = None
    if body is not None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=payload, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    opener = _opener(use_proxy)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, raw
    except urllib.error.URLError as e:
        raise JsbError(f"网络不可达：{e.reason}")


def basic_auth(client_id, client_secret):
    token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"