# -*- coding: utf-8 -*-
"""
抖音主页 aweme/post 采集器（路线 A：浏览器内 secsdk 生成 a_bogus + requests 发送）

流程：
  1) Playwright 打开目标主页，让页面加载 secsdk（webmssdk + runtime_bundler + sdk-glue + bdms）
  2) 在页面内用原生 XMLHttpRequest 发起目标接口请求 —— secsdk 的 XHR 拦截器会自动补 a_bogus
  3) 用 page.on('request') 截获【签名后的完整 URL】（含 a_bogus / timestamp）
  4) 用 requests + 页面 cookie 复用发送该签名 URL → 拿到明文 JSON
  5) 解析 aweme_list，输出主页视频信息

依赖：playwright, requests
用法：python douyin_fetch.py
"""
import sys, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
import requests

SEC_USER_ID = "MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y"
USER_URL = f"https://www.douyin.com/user/{SEC_USER_ID}"
API = "https://www.douyin.com/aweme/v1/web/aweme/post/"

# 业务查询参数（可改：max_cursor 翻页、count 条数）
def build_query(max_cursor=0, count=18):
    from urllib.parse import urlencode
    q = {
        "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
        "sec_user_id": SEC_USER_ID, "max_cursor": str(max_cursor),
        "locate_query": "false", "show_live_replay_strategy": "1", "need_time_list": "1",
        "time_list_query": "0", "whale_cut_token": "", "cut_version": "1",
        "count": str(count), "publish_video_strategy_type": "2", "from_user_page": "1",
        "update_version_code": "170400", "pc_client_type": "1", "pc_libra_divert": "Windows",
        "support_h265": "1", "support_dash": "0", "cpu_core_num": "20",
        "version_code": "290100", "version_name": "29.1.0", "cookie_enabled": "true",
        "screen_width": "1707", "screen_height": "960", "browser_language": "zh-CN",
        "browser_platform": "Win32", "browser_name": "Chrome", "browser_version": "140.0.0.0",
        "browser_online": "true", "engine_name": "Blink", "engine_version": "140.0.0.0",
        "os_name": "Windows", "os_version": "10", "device_memory": "8", "platform": "PC",
        "downlink": "10", "effective_type": "4g", "round_trip_time": "50",
    }
    return urlencode(q)


def fetch_signed_url(page, query, timeout=15.0):
    """在页面内用 XHR 触发 secsdk 签名，截获带 a_bogus 的完整 URL"""
    holder = {"url": None}
    url_to_match = API.split("//")[1]  # www.douyin.com/aweme/...

    def on_req(req):
        if "aweme/post" in req.url and "a_bogus=" in req.url:
            holder["url"] = req.url

    page.on("request", on_req)
    try:
        page.evaluate(
            """(q) => {
                const x = new XMLHttpRequest();
                x.open('GET', '/' + q);
                x.send();
            }""",
            "aweme/v1/web/aweme/post/?" + query,
        )
        deadline = time.time() + timeout
        while time.time() < deadline and not holder["url"]:
            page.wait_for_timeout(200)
    finally:
        page.remove_listener("request", on_req)
    return holder["url"]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1707, "height": 960},
        )
        page = ctx.new_page()
        print("[1/4] 打开主页，加载 secsdk ...")
        page.goto(USER_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        query = build_query(max_cursor=0, count=18)
        print("[2/4] 页面内触发签名，截获带 a_bogus 的 URL ...")
        signed_url = fetch_signed_url(page, query)
        if not signed_url:
            print("[X] 未截获签名 URL"); browser.close(); return
        print("      -> a_bogus 已生成，URL 长度 =", len(signed_url))

        cookies = ctx.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        browser.close()

    print("[3/4] 用 requests 复用 cookie 发送签名 URL ...")
    headers = {
        "accept": "application/json, text/plain, */*",
        "referer": USER_URL,
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
        "cookie": cookie_str,
    }
    r = requests.get(signed_url, headers=headers, timeout=20)
    print("      HTTP", r.status_code, "len", len(r.text))
    data = r.json()
    aweme_list = data.get("aweme_list") or []
    print("[4/4] status_code =", data.get("status_code"), "| 视频数 =", len(aweme_list))

    with open("aweme_post_latest.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n===== 主页视频列表 =====")
    for i, a in enumerate(aweme_list, 1):
        st = a.get("statistics", {})
        print(f"{i:2d}. {a.get('aweme_id')} | {a.get('desc','')[:40]}")
        print(f"    点赞{st.get('digg_count')} 评论{st.get('comment_count')} "
              f"收藏{st.get('collect_count')} 分享{st.get('share_count')}")
    print("\n已保存 aweme_post_latest.json")


if __name__ == "__main__":
    main()
