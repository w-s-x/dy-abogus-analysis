# -*- coding: utf-8 -*-
"""
douyin_identity.py —— 纯协议刷新抖音「身份」（cookie），无需 Playwright。

背景（为什么能做到纯协议）
--------------------------
抖音只在「通过 acrawler 挑战的浏览器请求」上**首次**下发 UIFID/ttwid，
所以「从零引导」仍需要一次浏览器。但只要手上有一个【曾经可用】的 cookie，
就可以用 curl_cffi（伪造 Chrome 的 TLS/HTTP2 指纹）纯协议访问首页 + 用户页：
服务端会识别旧身份并通过（返回完整页面），同时**续发**一版新的
ttwid / UIFID / web_sign_token。合并进旧 cookie 后即为可用身份
（实测：HTTP 200 / status_code 0 / 17 条）。

=> 首次引导用浏览器一次；此后刷新全程纯协议，约 1 秒，不再需要 Playwright。

两条铁律
--------
1. **只刷新 cookie，绝不覆盖 browser_ls_fresh.json。**
   实测：新 dump 出来的 localStorage 只要含 `xmst`，签名会整体失效
   （HTTP 200 但 len=0）。旧 localStorage 请原样保留。
2. 种子 cookie 若已彻底失效（服务端不再返回完整页面），会抛
   RuntimeError，此时才需要退回浏览器 dump_fresh_env.py 重新引导。

依赖：curl_cffi （uv pip install curl_cffi）
用法：
    python douyin_identity.py            # 纯协议刷新 cookie_fresh2.txt
    python douyin_identity.py --verify   # 刷新后再打一次接口做验证
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(BASE_DIR, "cookie_fresh2.txt")

# 采集目标（与 douyin_node_fetch.py 保持一致）
SEC_DEFAULT = "MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y"

# 刷新用请求头；UA 交给 curl_cffi 的 impersonate 处理，保证与 TLS 指纹自洽
REFRESH_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "accept-language": "zh-CN,zh;q=0.9",
}

# 完整页面（非挑战页）的最小长度，用于判断种子是否仍有效
_FULL_PAGE_MIN = 100_000


def parse_cookie(text):
    d = {}
    for kv in text.strip().split("; "):
        if "=" in kv:
            k, v = kv.split("=", 1)
            d[k.strip()] = v
    return d


def join_cookie(d):
    return "; ".join(f"{k}={v}" for k, v in d.items())


def load_cookie(path=COOKIE_FILE):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def save_cookie(ck, path=COOKIE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        f.write(ck)


def refresh_cookie(seed=None, sec_user_id=SEC_DEFAULT, timeout=25):
    """用已有 cookie 作种子，纯协议换一版新鲜身份。返回合并后的 cookie 串。

    只做两件事：抓首页 + 抓用户页，把服务端 Set-Cookie 合并回种子 cookie。
    """
    try:
        from curl_cffi import requests as creq
    except ImportError as e:
        raise RuntimeError("需要 curl_cffi：uv pip install curl_cffi") from e

    seed = seed or load_cookie()
    merged = parse_cookie(seed)

    s = creq.Session(impersonate="chrome")
    s.headers.update(REFRESH_HEADERS)
    s.headers["cookie"] = seed

    urls = ("https://www.douyin.com/", f"https://www.douyin.com/user/{sec_user_id}")
    for url in urls:
        r = s.get(url, timeout=timeout)
        if r.status_code != 200 or len(r.text) < _FULL_PAGE_MIN:
            raise RuntimeError(
                "刷新被拦：%s -> HTTP %s len=%s（种子 cookie 可能已彻底失效，"
                "需用浏览器重新引导 dump_fresh_env.py）"
                % (url, r.status_code, len(r.text))
            )

    merged.update(s.cookies.get_dict())
    return join_cookie(merged)


def cookie_age_seconds(path=COOKIE_FILE):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return float("inf")


def maybe_refresh(max_age_sec=1800, path=COOKIE_FILE, sec_user_id=SEC_DEFAULT):
    """按 mtime 判断是否值得刷新，避免每次运行都打两枪。

    返回 (cookie, refreshed: bool)。
    """
    if cookie_age_seconds(path) < max_age_sec:
        return load_cookie(path), False
    ck = refresh_cookie(load_cookie(path), sec_user_id=sec_user_id)
    save_cookie(ck, path)
    return ck, True


def _verify(cookie):
    """用签名链打一次接口验证 cookie 是否可用（需 node + iv8rs）。"""
    import json
    import requests
    import douyin_sign
    from douyin_sign import sign

    q = ("device_platform=webapp&aid=6383&channel=channel_pc_web&sec_user_id=" +
         SEC_DEFAULT + "&max_cursor=0&count=18&from_user_page=1&version_code=290100&platform=PC")
    final, headers = sign("/aweme/v1/web/aweme/post/", q,
                          referer=f"https://www.douyin.com/user/{SEC_DEFAULT}", cookie=cookie)
    r = requests.get(final, headers=headers, timeout=20)
    ok = False
    try:
        j = r.json()
        ok = (j.get("status_code") == 0 and (j.get("aweme_list") or []))
        n = len(j.get("aweme_list") or [])
    except Exception:
        n = -1
    print("  验证: HTTP %s len=%s aweme=%s -> %s" % (r.status_code, len(r.text), n,
                                                     "✅ 可用" if ok else "❌ 不可用"))
    return ok


def main():
    verify = "--verify" in sys.argv
    t0 = time.time()
    old = load_cookie()
    old_uid = parse_cookie(old).get("UIFID_TEMP", "")
    print("纯协议刷新身份（curl_cffi / Chrome 指纹，无浏览器）...")
    print("  旧 UIFID_TEMP:", old_uid[:60], "...")
    try:
        new = refresh_cookie(old)
    except Exception as e:
        print("  ❌ 刷新失败:", e)
        sys.exit(1)
    save_cookie(new)
    new_uid = parse_cookie(new).get("UIFID_TEMP", "")
    print("  新 UIFID_TEMP:", new_uid[:60], "...")
    print("  cookie 键数:", len(parse_cookie(new)), "| 耗时 %.2fs" % (time.time() - t0))
    print("  已写回:", COOKIE_FILE)
    if verify:
        _verify(new)


if __name__ == "__main__":
    main()
