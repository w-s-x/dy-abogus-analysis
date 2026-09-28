# -*- coding: utf-8 -*-
"""
douyin_node_fetch.py —— 纯协议方案（无浏览器依赖）

流程:
  [1/3] Node.js(真实V8) 跑 bdms 生成 a_bogus
  [2/3] iv8rs SDKRuntime.webSignUrl 补 uifid/timestamp/x-secsdk-web-signature
  [3/3] requests 取数；若返回空（身份失效）→ 纯协议刷新 cookie 后自动重试一次

身份刷新走 douyin_identity.py（curl_cffi，无需 Playwright）。
依赖: node+jsdom / iv8rs / requests / curl_cffi
"""
import subprocess, json, sys, time, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from urllib.parse import quote
import iv8_rs

SEC = "MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y"
Q = ("device_platform=webapp&aid=6383&channel=channel_pc_web&sec_user_id=" + SEC +
     "&max_cursor=0&count=18&from_user_page=1&version_code=290100&platform=PC")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

R = "recycle/"
def rd(p): return open(R + p, encoding="utf-8", errors="replace").read()

U = {"runtime": "https://lf-security.bytegoofy.com/obj/security-secsdk-gray/runtime_bundler_34.js",
     "webmssdk": "https://lf-c-flwb.bytetos.com/obj/rc-client-security/c-webmssdk/1.0.0.20/webmssdk.es5.js",
     "glue": "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/glue/1.0.0.64-fix.01/sdk-glue.js",
     "bdms": "https://p-pc-weboff.byteimg.com/tos-cn-i-9r5gewecjs/bdms_1.0.1.19_fix.js",
     "captcha": "https://lf-rc1.yhgfb-cn-static.com/obj/rc-verifycenter/sec_sdk_build/4.0.28/captcha/index.js"}


# ---------- 第1步: Node 生成 a_bogus ----------
def gen_a_bogus(query):
    out = subprocess.run(["node", "node_sign.js", query], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=120)
    ab = out.stdout.strip()
    if not ab or len(ab) < 100:
        print("Node sign failed:", out.stdout[-400:], out.stderr[-400:]); sys.exit(1)
    return ab


# ---------- 第2步: iv8rs webSignUrl 补全 uifid/timestamp/x-secsdk-web-signature ----------
def web_sign_url(base_url, cookie):
    LS = json.load(open("browser_ls_fresh.json", encoding="utf-8"))
    REAL_MS = int(time.time() * 1000)
    TF = """(function(){var R=__REAL__;try{Object.defineProperty(performance,'timeOrigin',{value:R-Math.floor(performance.now()),configurable:true});}catch(e){}
var _D=Date,_n=function(){return Math.floor(performance.timeOrigin+performance.now());};function M(){if(arguments.length===0)return new _D(_n());if(arguments.length===1)return new _D(arguments[0]);return new _D(arguments[0],arguments[1],arguments[2]||1,arguments[3]||0,arguments[4]||0,arguments[5]||0,arguments[6]||0);}M.now=_n;M.prototype=_D.prototype;window.Date=M;})();""".replace("__REAL__", str(REAL_MS))
    LS_JS = "(function(){var d=" + json.dumps(LS, ensure_ascii=True) + ";for(var k in d){try{localStorage.setItem(k,d[k]);}catch(e){}}})();"
    shim = open("xhr_shim.js", encoding="utf-8").read()
    ctx = iv8_rs.JSContext()
    try:
        srcs = {"runtime": rd("runtime_bundler_34.js"), "webmssdk": open("webmssdk.js", encoding="utf-8").read(),
                "glue": rd("sdk-glue.js"), "captcha": rd("captcha_index.js"), "bdms": rd("bdms_fix.js")}
        for k in U:
            ctx.add_resource(U[k], srcs[k], status=200, headers={"content-type": "application/javascript"})
        ctx.expose("__pylog", lambda m: None)
        ctx.eval("window._sdkGlueVersionMap={sdkGlueVersion:'1.0.0.64-fix.01',bdmsVersion:'1.0.1.19-fix.01',captchaVersion:'4.0.10'};")
        sc = [("Set-Cookie", f"{kv.strip()}; path=/") for kv in cookie.split("; ") if "=" in kv]
        html = ("<!doctype html><html><body>"
                f'<script>{TF}</script><script>{LS_JS}</script>'
                f'<script src="{U["runtime"]}"></script><script src="{U["webmssdk"]}"></script>'
                f'<script src="{U["glue"]}"></script><script>{shim}</script>'
                f'<script src="{U["bdms"]}"></script>'
                f'<script src="{U["captcha"]}"></script></body></html>')
        ctx.page_load_with_headers(html, base_url="https://www.douyin.com/user/x", headers=sc)
        for _ in range(5):
            ctx.eval("__iv8__.eventLoop.drain()"); ctx.eval("__iv8__.eventLoop.advance(500)")
        ctx.eval("window.__sign=null;")
        ctx.eval("(function(){try{var g=window.SDKRuntime&&window.SDKRuntime.global; if(g&&typeof g.webSignUrl==='function'){window.__sign=JSON.stringify(g.webSignUrl('" + base_url.replace("'", "\\'") + "'));}}catch(e){window.__sign='ERR '+e.message;}})();")
        signed = ctx.eval("String(window.__sign||'')")
    finally:
        ctx.close()
    try:
        final = json.loads(signed).get("url") or base_url
    except Exception:
        final = base_url
    return final


def build_final(cookie):
    print("[1/3] Node.js 真实V8 生成 a_bogus ...")
    ab = gen_a_bogus(Q)
    print(f"    a_bogus len={len(ab)}")
    print("[2/3] iv8rs webSignUrl 补全 uifid/timestamp/x-secsdk-web-signature ...")
    base = f"https://www.douyin.com/aweme/v1/web/aweme/post/?{Q}&a_bogus={quote(ab, safe='')}"
    final = web_sign_url(base, cookie)
    print("    final url:", final[:120], "...")
    return final


def request(final, cookie):
    h = {"accept": "application/json, text/plain, */*", "referer": f"https://www.douyin.com/user/{SEC}",
         "user-agent": UA, "cookie": cookie}
    return requests.get(final, headers=h, timeout=20)


def main():
    cookie = open("cookie_fresh2.txt", encoding="utf-8").read().strip()
    final = build_final(cookie)
    print("[3/3] requests 请求 ...")
    r = request(final, cookie)
    print("HTTP", r.status_code, "len", len(r.text))

    if len(r.text) == 0:
        print("    [空响应] 身份可能已失效，尝试纯协议刷新 cookie（无需 Playwright）...")
        try:
            import douyin_identity
            cookie = douyin_identity.refresh_cookie(cookie)
            douyin_identity.save_cookie(cookie)
            print("    刷新成功，重新签名并重试 ...")
            final = build_final(cookie)
            r = request(final, cookie)
            print("HTTP", r.status_code, "len", len(r.text))
        except Exception as e:
            print("    纯协议刷新失败:", e)

    try:
        j = r.json()
        print("status_code:", j.get("status_code"), "aweme:", len(j.get("aweme_list") or []))
        aw = j.get("aweme_list") or []
        for i, a in enumerate(aw, 1):
            st = a.get("statistics", {})
            print(f"  {i}. {a.get('aweme_id')} | {a.get('desc','')[:36]} | 赞{st.get('digg_count')} | 评{st.get('comment_count')}")
        json.dump(j, open("aweme_node.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("saved aweme_node.json")
    except Exception as e:
        print("json err", e, repr(r.text[:200]))


if __name__ == "__main__":
    main()
