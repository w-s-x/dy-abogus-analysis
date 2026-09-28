# -*- coding: utf-8 -*-
"""
dump_fresh_env.py —— 【一次性引导】用 Playwright 打开目标主页，导出身份：
    cookie_fresh2.txt        新鲜 cookie
    browser_ls_fresh.json    localStorage（含 EC 私钥/证书）

日常刷新 cookie 请用 douyin_identity.py（纯协议，约 1~2 秒），**不需要本脚本**。
只有种子 cookie 已彻底失效（连完整页面都拿不到）时，才需要用本脚本重新引导。

⚠️ 写出的 localStorage 会主动剔除 `xmst` 键：
   实测新 dump 的 LS 只要含 `xmst`，签名会整体失效（HTTP 200 但 len=0）。
"""
import asyncio, json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

SEC = "MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        pg = await ctx.new_page()
        await pg.goto("https://www.douyin.com/user/" + SEC, wait_until="domcontentloaded", timeout=60000)
        # 等 SDK 种下 UIFID_TEMP（最多 20s），再留 2s 让其写完最终值
        for _ in range(40):
            if any(c["name"] == "UIFID_TEMP" for c in await ctx.cookies()):
                break
            await pg.wait_for_timeout(500)
        await pg.wait_for_timeout(2000)

        ls = await pg.evaluate("() => { const o={}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=localStorage.getItem(k);} return o; }")
        cookies = await ctx.cookies()
        ck = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        stripped = ls.pop("xmst", None) is not None

        json.dump(ls, open("browser_ls_fresh.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open("cookie_fresh2.txt", "w", encoding="utf-8").write(ck)
        print("saved browser_ls_fresh.json (%d keys), cookie_fresh2.txt" % len(ls))
        print("  xmst 已剔除:", stripped)
        for k in ("security-sdk/s_sdk_crypt_sdk", "web_secsdk_runtime_cache", "security-sdk/s_sdk_server_cert_key", "web_runtime_security_uid", "=^_^=athena_web_id"):
            if k in ls:
                print(f"  {k}: {ls[k][:150]}")
        for c in cookies:
            if "uifid" in c["name"].lower():
                print(f"  {c['name']} = {c['value'][:100]}")
        await b.close()


asyncio.run(main())
