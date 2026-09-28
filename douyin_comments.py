# -*- coding: utf-8 -*-
"""
douyin_comments.py —— 抖音「视频评论」采集脚本（独立脚本，不影响 douyin_node_fetch.py）

目标接口：GET https://www.douyin.com/aweme/v1/web/comment/list/
签名复用：douyin_sign.sign()（与主页视频采集同一套签名链路，完全解耦）

背景说明（无登录的现实）：
    /aweme/v1/web/comment/list/ 返回明文 JSON，但必须带完整签名（a_bogus + uifid +
    timestamp + x-secsdk-web-signature 头 + 新鲜 cookie）。
    未登录状态下服务端会做限制：通常只放行第一页（cursor=0，约 20 条），
    has_more 可能仍为 1，但继续翻页会返回空列表或 status_code 异常。
    所以本脚本策略是「能拿多少拿多少」：逐页请求，遇到空页/异常立即停止，并如实报告。

用法：
    python douyin_comments.py                       # 采集默认视频
    python douyin_comments.py 7684183547095043374   # 指定 aweme_id
    python douyin_comments.py <aweme_id> --max-pages 5
"""
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta

from douyin_sign import sign, load_cookie, UA, HOST

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 目标：主页第一个视频
DEFAULT_AWEME_ID = "7684183547095043374"
CST = timezone(timedelta(hours=8))


def _fmt_time(ts):
    try:
        return datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _pick_user(u):
    u = u or {}
    return {
        "uid": u.get("uid"),
        "sec_uid": u.get("sec_uid"),
        "nickname": u.get("nickname"),
        "unique_id": u.get("unique_id"),
        "custom_verify": u.get("custom_verify"),
    }


def parse_comment(c):
    """把单条评论归一化成精简字段（便于后续处理）。"""
    return {
        "cid": c.get("cid"),
        "text": c.get("text"),
        "create_time": c.get("create_time"),
        "create_time_str": _fmt_time(c.get("create_time")),
        "digg_count": c.get("digg_count", 0),
        "reply_comment_total": c.get("reply_comment_total", 0),
        "ip_label": c.get("ip_label", ""),
        "user_digged": c.get("user_digged", 0),
        "image_count": len(c.get("image_list") or []),
        "is_author": bool(c.get("is_author")),
        "user": _pick_user(c.get("user")),
        # 一级评论里内嵌的少量二级回复（无登录一般也是空的）
        "reply_comment": [
            {
                "cid": r.get("cid"),
                "text": r.get("text"),
                "digg_count": r.get("digg_count", 0),
                "reply_to_username": r.get("reply_to_username") or (r.get("user") or {}).get("nickname"),
                "user": _pick_user(r.get("user")),
            }
            for r in (c.get("reply_comment") or [])
        ],
    }


def build_query(aweme_id, cursor, count):
    """构造 comment/list 的 query（a_bogus 由 sign 追加，不要手写）。"""
    import requests  # noqa: F401  (仅为保持一致；cookie 里取 fp)
    cookie = load_cookie()
    parts = [
        "device_platform=webapp",
        "aid=6383",
        "channel=channel_pc_web",
        f"aweme_id={aweme_id}",
        f"cursor={cursor}",
        f"count={count}",
        "item_type=0",
        "insert_ids=",
        "whale_cut_token=",
        "cut_version=1",
        "rcFT=",
        "pc_client_type=1",
        "version_code=290100",
        "version_name=29.1.0",
        "cookie_enabled=true",
        "screen_width=1920",
        "screen_height=1080",
        "browser_language=zh-CN",
        "browser_platform=Win32",
        "browser_name=Chrome",
        "browser_version=147.0.0.0",
        "browser_online=true",
        "engine_name=Blink",
        "engine_version=147.0.0.0",
        "os_name=Windows",
        "os_version=10",
        "cpu_core_num=20",
        "device_memory=16",
        "platform=PC",
        "downlink=10",
        "effective_type=4g",
        "round_trip_time=50",
    ]
    return "&".join(parts)


def fetch_page(aweme_id, cursor, count=20, referer=None, retries=2):
    """请求一页评论，返回原始 json。"""
    import requests

    query = build_query(aweme_id, cursor, count)
    final_url, headers = sign(
        "/aweme/v1/web/comment/list/",
        query,
        referer=referer or f"{HOST}/video/{aweme_id}",
    )
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(final_url, headers=headers, timeout=20)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(1.0)
                continue
            return r.json()
        except Exception as e:
            last_err = repr(e)
            time.sleep(1.0)
    raise RuntimeError(f"请求失败: {last_err}")


def collect_comments(aweme_id=DEFAULT_AWEME_ID, count=25, max_pages=50,
                     sleep=1.0, verbose=True):
    """逐页采集评论，返回 dict（含 comments / 统计 / 终止原因）。"""
    all_comments = []
    seen_cids = set()
    cursor = 0
    page = 0
    total = None
    stop_reason = None
    referer = f"{HOST}/user/MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y?modal_id={aweme_id}"

    while page < max_pages:
        page += 1
        if verbose:
            print(f"[page {page}] cursor={cursor} ...")
        try:
            j = fetch_page(aweme_id, cursor, count=count, referer=referer)
        except Exception as e:
            stop_reason = f"请求异常: {e}"
            if verbose:
                print("   ", stop_reason)
            break

        status = j.get("status_code")
        comments = j.get("comments") or []
        if total is None:
            total = j.get("total")
        if verbose:
            print(f"    status_code={status} 本页={len(comments)} total={j.get('total')} "
                  f"has_more={j.get('has_more')} next_cursor={j.get('cursor')}")

        if status not in (0, None):
            stop_reason = f"status_code={status}（被风控/需登录）"
            break
        if not comments:
            stop_reason = "本页返回空（无登录限制或已到末尾）"
            break

        new = 0
        for c in comments:
            cid = c.get("cid")
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            all_comments.append(parse_comment(c))
            new += 1

        has_more = j.get("has_more")
        next_cursor = j.get("cursor")
        if not has_more or next_cursor is None or next_cursor == cursor:
            stop_reason = "has_more=0 或 cursor 未前进（采集完成）"
            break
        if new == 0:
            stop_reason = "本页无新评论（服务端在重复返回）"
            break
        cursor = next_cursor
        time.sleep(sleep)
    else:
        stop_reason = f"达到最大页数限制 max_pages={max_pages}"

    return {
        "aweme_id": aweme_id,
        "total_reported": total,
        "collected": len(all_comments),
        "pages": page,
        "stop_reason": stop_reason,
        "comments": all_comments,
    }


def main():
    ap = argparse.ArgumentParser(description="抖音视频评论采集（无登录，能拿多少拿多少）")
    ap.add_argument("aweme_id", nargs="?", default=DEFAULT_AWEME_ID, help="视频 aweme_id")
    ap.add_argument("--count", type=int, default=20, help="每页条数（默认 20）")
    ap.add_argument("--max-pages", type=int, default=50, help="最大页数（默认 50）")
    ap.add_argument("--sleep", type=float, default=1.0, help="翻页间隔秒（默认 1.0）")
    ap.add_argument("--out", default=None, help="输出 JSON 路径（默认 comments_<id>.json）")
    args = ap.parse_args()

    print(f"=== 采集视频评论 aweme_id={args.aweme_id} ===")
    res = collect_comments(
        aweme_id=args.aweme_id,
        count=args.count,
        max_pages=args.max_pages,
        sleep=args.sleep,
    )

    print("\n--- 结果 ---")
    print(f"服务端报告总数 total : {res['total_reported']}")
    print(f"实际拿到评论数       : {res['collected']}")
    print(f"翻页数               : {res['pages']}")
    print(f"停止原因             : {res['stop_reason']}")
    for i, c in enumerate(res["comments"][:15], 1):
        nick = (c["user"] or {}).get("nickname") or ""
        txt = (c["text"] or "").replace("\n", " ")
        print(f"  {i:2d}. [{c['digg_count']:>5}赞] {nick}: {txt[:50]}")

    out = args.out or f"comments_{args.aweme_id}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()
