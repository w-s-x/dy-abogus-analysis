# -*- coding: utf-8 -*-
"""
douyin_sign.py —— 抖音 web 签名模块（解耦、可复用）

职责：把「任意一个 querystring」变成「带完整签名的最终 URL + 请求头」。
内部 3 步链路：
    1) Node.js(真实 V8) 跑 bdms           → 生成 a_bogus
    2) iv8rs  SDKRuntime.webSignUrl       → 补 uifid / timestamp / x-secsdk-web-signature
    3) 组装最终 URL 与 headers

设计目标：调用方只关心「我要请求哪个接口、参数是什么」，不关心签名细节。
任何新接口（主页视频、评论列表、二级评论……）都可以直接复用 sign()。

用法：
    from douyin_sign import sign
    final_url, headers = sign(
        path="/aweme/v1/web/comment/list/",
        query="aweme_id=xxx&cursor=0&count=20&item_type=0",
        referer="https://www.douyin.com/video/xxx",
    )

依赖（与本项目现有文件保持一致）：
    node_sign.js            Node 侧 a_bogus 生成器（保持原样，不要改）
    cookie_fresh2.txt       浏览器导出新鲜 cookie
    browser_ls_fresh.json   浏览器导出 localStorage（含 EC 私钥/证书）
    xhr_shim.js             iv8rs 侧 XHR 包装
    recycle/*.js            5 个安全 SDK 脚本
    iv8_rs                  本机虚拟环境  内
"""
import subprocess
import json
import time
import os
import sys
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "https://www.douyin.com"

# 完整 Chrome UA —— 必须是完整串，否则 a_bogus 指纹不自洽会被拒
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

# 5 个安全 SDK 脚本的线上地址（iv8rs 用，与 node_sign.js 内部一致）
SDK_URLS = {
    "runtime": "https://lf-security.bytegoofy.com/obj/security-secsdk-gray/runtime_bundler_34.js",
    "webmssdk": "https://lf-c-flwb.bytetos.com/obj/rc-client-security/c-webmssdk/1.0.0.20/webmssdk.es5.js",
    "glue": "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/glue/1.0.0.64-fix.01/sdk-glue.js",
    "bdms": "https://p-pc-weboff.byteimg.com/tos-cn-i-9r5gewecjs/bdms_1.0.1.19_fix.js",
    "captcha": "https://lf-rc1.yhgfb-cn-static.com/obj/rc-verifycenter/sec_sdk_build/4.0.28/captcha/index.js",
}


def _read(path):
    with open(os.path.join(BASE_DIR, path), encoding="utf-8", errors="replace") as f:
        return f.read()


def load_cookie():
    return _read("cookie_fresh2.txt").strip()


def gen_a_bogus(query, node_cwd=None):
    """第1步：用 Node.js(真实 V8 + jsdom) 跑 bdms，得到 a_bogus。"""
    out = subprocess.run(
        ["node", "node_sign.js", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=node_cwd or BASE_DIR,
    )
    ab = (out.stdout or "").strip()
    if not ab or len(ab) < 100:
        raise RuntimeError(
            "node_sign.js 生成 a_bogus 失败: stdout=%r stderr=%r"
            % (out.stdout[-400:], out.stderr[-400:])
        )
    return ab


def web_sign_url(base_url, cookie):
    """第2步：用 iv8rs 的 SDKRuntime.global.webSignUrl 补 uifid/timestamp/签名头。"""
    import iv8_rs

    # iv8rs 的 Date.now() 被冻结，需要重建 Date / performance.timeOrigin
    real_ms = int(time.time() * 1000)
    tf = (
        "(function(){var R=__REAL__;"
        "try{Object.defineProperty(performance,'timeOrigin',{value:R-Math.floor(performance.now()),configurable:true});}catch(e){}"
        "var _D=Date,_n=function(){return Math.floor(performance.timeOrigin+performance.now());};"
        "function M(){if(arguments.length===0)return new _D(_n());"
        "if(arguments.length===1)return new _D(arguments[0]);"
        "return new _D(arguments[0],arguments[1],arguments[2]||1,arguments[3]||0,arguments[4]||0,arguments[5]||0,arguments[6]||0);}"
        "M.now=_n;M.prototype=_D.prototype;window.Date=M;})();"
    ).replace("__REAL__", str(real_ms))

    ls = json.loads(_read("browser_ls_fresh.json"))
    ls_js = "(function(){var d=" + json.dumps(ls, ensure_ascii=True) + ";for(var k in d){try{localStorage.setItem(k,d[k]);}catch(e){}}})();"
    shim = _read("xhr_shim.js")

    ctx = iv8_rs.JSContext()
    try:
        srcs = {
            "runtime": _read("recycle/runtime_bundler_34.js"),
            "webmssdk": _read("webmssdk.js"),
            "glue": _read("recycle/sdk-glue.js"),
            "captcha": _read("recycle/captcha_index.js"),
            "bdms": _read("recycle/bdms_fix.js"),
        }
        for k in SDK_URLS:
            ctx.add_resource(SDK_URLS[k], srcs[k], status=200,
                             headers={"content-type": "application/javascript"})
        ctx.expose("__pylog", lambda m: None)
        ctx.eval("window._sdkGlueVersionMap={sdkGlueVersion:'1.0.0.64-fix.01',bdmsVersion:'1.0.1.19-fix.01',captchaVersion:'4.0.10'};")
        sc = [("Set-Cookie", f"{kv.strip()}; path=/") for kv in cookie.split("; ") if "=" in kv]
        html = (
            "<!doctype html><html><body>"
            f"<script>{tf}</script><script>{ls_js}</script>"
            f'<script src="{SDK_URLS["runtime"]}"></script><script src="{SDK_URLS["webmssdk"]}"></script>'
            f'<script src="{SDK_URLS["glue"]}"></script><script>{shim}</script>'
            f'<script src="{SDK_URLS["bdms"]}"></script>'
            f'<script src="{SDK_URLS["captcha"]}"></script></body></html>'
        )
        ctx.page_load_with_headers(html, base_url=HOST + "/user/x", headers=sc)
        for _ in range(5):
            ctx.eval("__iv8__.eventLoop.drain()")
            ctx.eval("__iv8__.eventLoop.advance(500)")
        ctx.eval("window.__sign=null;")
        safe = base_url.replace("'", "\\'")
        ctx.eval(
            "(function(){try{var g=window.SDKRuntime&&window.SDKRuntime.global;"
            "if(g&&typeof g.webSignUrl==='function'){window.__sign=JSON.stringify(g.webSignUrl('" + safe + "'));}"
            "}catch(e){window.__sign='ERR '+e.message;}})();"
        )
        sign = ctx.eval("String(window.__sign||'')")
    finally:
        ctx.close()

    try:
        obj = json.loads(sign)
    except Exception:
        return base_url, {}
    return (obj.get("url") or base_url), (obj.get("headers") or {})


def sign(path, query, referer=None, cookie=None):
    """一站式签名：返回 (final_url, request_headers)。

    path    : 接口路径，例如 "/aweme/v1/web/comment/list/"
    query   : 不含 a_bogus 的 querystring（建议已带 verifyFp/fp）
    referer : 页面 referer，默认用首页
    """
    cookie = cookie or load_cookie()
    query = query.lstrip("?&")
    if not query:
        raise ValueError("query 不能为空")

    a_bogus = gen_a_bogus(query)
    base_url = f"{HOST}{path}?{query}&a_bogus={quote(a_bogus, safe='')}"
    final_url, extra_headers = web_sign_url(base_url, cookie)

    headers = {
        "accept": "application/json, text/plain, */*",
        "referer": referer or (HOST + "/"),
        "user-agent": UA,
        "cookie": cookie,
    }
    if extra_headers:
        for k, v in extra_headers.items():
            headers[str(k).lower()] = v
    return final_url, headers


if __name__ == "__main__":
    # 自测：签名一个主页视频接口并打印结果
    SEC = "MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y"
    q = ("device_platform=webapp&aid=6383&channel=channel_pc_web&sec_user_id=" + SEC +
         "&max_cursor=0&count=18&from_user_page=1&version_code=290100&platform=PC")
    u, h = sign("/aweme/v1/web/aweme/post/", q, referer=f"{HOST}/user/{SEC}")
    print("final_url:", u[:160], "...")
    print("headers keys:", list(h.keys()))
