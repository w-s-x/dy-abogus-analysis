# 抖音 Web 纯协议采集（a_bogus 签名逆向）

> ## ⚠️ 免责声明
>
> - 本项目**仅供技术研究与学习交流**，用于理解 Web 前端签名（`a_bogus` / JSVMP）的实现原理。
> - 请勿将本项目用于任何**商业用途、高频批量抓取、数据倒卖**或侵犯他人隐私、版权的行为。
> - 使用者应自行遵守**目标站点的服务条款（ToS）**、`robots.txt` 及所在地区的法律法规；因使用本项目产生的一切后果由使用者自行承担。
> - 项目不含任何登录凭据、密钥或抓取数据，相关身份信息需使用者自行获取，作者不对其合法性作任何担保。
> - 若本项目内容侵犯了您的权益，请联系删除。

---

用纯协议方式采集抖音 Web 端数据（主页视频列表、视频评论），不依赖真实浏览器完成日常取数。

项目核心是**复现抖音请求侧的 `a_bogus` 签名链**——接口响应本身是明文 JSON，唯一的门槛在于请求必须携带合法签名。

---

## 一、原理：难在哪

抓包可见 `/aweme/v1/web/aweme/post/`（主页视频）与 `/aweme/v1/web/comment/list/`（评论）的响应都是**明文 JSON**，没有加密。真正的门槛全在请求侧，URL 必须带上完整签名：

```
GET /aweme/v1/web/aweme/post/?<业务query>
    &verifyFp=verify_xxx&fp=verify_xxx
    &a_bogus=<签名值>          ← 必需，去掉返回空
    &uifid=<环境指纹>&timestamp=<unix秒>
    &x-secsdk-web-signature=<请求头签名>
```

实测各参数的必需性：

| 参数                                | 必需性  | 说明                             |
| ----------------------------------- | ------- | -------------------------------- |
| `a_bogus`                           | ✅ 必需 | 去掉直接返回空                   |
| `uifid` / `timestamp`               | ✅ 必需 | 缺失报 `Uifid Not Found`         |
| `x-secsdk-web-signature`（头）      | ✅ 必需 | 缺失报 `Signature Not Found`     |
| `verifyFp` / `fp`                   | 🟡 建议 | 是签名明文的一部分，真实页面必带 |
| cookie（`UIFID_TEMP` / `ttwid` 等） | ✅ 必需 | 缺失触发风控                     |

### a_bogus 的签名明文

通过 hook 标准库函数抓到签名原文（两端一致验证）：

```
<UIFID_TEMP 全值>_<unix时间戳>_<UA 的 MD5>_<完整 query>
```

即 `a_bogus` 绑定 **cookie 中的 UIFID_TEMP + 时间戳 + User-Agent + 全部 query 参数**，因此**每次请求都要现场重新生成**，改动任一参数都会失效。

### 生成者：bdms（JSVMP 字节码）

CDP 断点跟栈确认的调用链：

```
业务代码 → axios → dtrait-core → XHR.send 包装层
  → captcha → bdms_1.0.1.19_fix.js   ← ★ a_bogus 在此诞生
  → sdk-glue → runtime_bundler → 原生 XHR.send（此时 URL 已带 a_bogus）
```

`bdms` 是一个 **JSVMP**（自解释字节码虚拟机），a_bogus 算法全部编译成自定义字节码，静态搜索所有 SDK 文件都找不到 `a_bogus` 明文字符串，**无法靠静态还原重写算法**。

### 破局点：给它一个真 V8

同一段 bdms 字节码，在不同引擎上的实测结果：

| 引擎                                    | a_bogus 长度 | 服务端     | 结论     |
| --------------------------------------- | ------------ | ---------- | -------- |
| 真实 Chrome                             | 184 / 188    | ✅ 200     | 基准     |
| iv8rs（Rust V8 沙箱 + JS polyfill DOM） | 192 / 196    | ❌ 空响应  | 被拒     |
| **Node.js 真实 V8 + jsdom**             | 192          | ✅ **200** | **采用** |
| Node + jsdom 默认 UA                    | 160          | ❌ 403     | UA 不对  |

关键认知：**签名长度本身不固定**，服务端校验的是"签名值与所声称的指纹（UA/cookie）是否自洽"。iv8rs 被拒不是因为算错，而是其 polyfill 环境与真实 V8 有细微差异，导致 VM 中间值不自洽（这种错不报异常，只产出"微妙不对"的结果，极难排查）。

> 一句话：JSVMP 是字节码自解释的，只要引擎语义标准，算法**不需要重写**。想省事，就给它一个货真价实的 V8。

### 采用的混合签名链

签名分两段，各用最擅长的引擎：

1. **a_bogus** —— `bdms` 生成，用 **Node.js 真实 V8 + jsdom** 跑原字节码（`node_sign.js`）。
2. **uifid / timestamp / x-secsdk-web-signature** —— `SDKRuntime.global.webSignUrl` 生成，属**纯 JS 计算**，用 **iv8rs** 进程内补齐最顺手。

随后用 `requests` 发送最终 URL 取数。

---

## 二、怎么用

### 1. 环境准备

```powershell
# Node + jsdom（用国内镜像加速）
npm config set registry https://registry.npmmirror.com
npm i jsdom --no-audit --no-fund

# Python 3.13 + iv8rs + requests
uv venv iv8rs-lab
.\iv8rs-lab\Scripts\pip install ming-iv8-rs requests
```

### 2. 抓取 secsdk 厂商脚本（不在仓库内，需自行下载）

本项目签名依赖抖音的 secsdk 五件套（**它们指向线上地址、会随版本更新，请自行抓取，不入库**），放到项目根目录与 `recycle/` 下：

```
webmssdk.js                      ← 底层 VM
recycle/runtime_bundler_34.js    ← 策略引擎
recycle/sdk-glue.js              ← 模块装配器（暴露 _SdkGlueInit）
recycle/bdms_fix.js              ← ★ a_bogus 主角
recycle/captcha_index.js         ← 验证中心 SDK
```

> `bdms_fix.js` 相对原始 bdms 有 2 处兼容补丁（沙箱需要，Node/jsdom 下无害）：模块 394 的 `Symbol.toStringTag` 赋值包 try-catch、VM 执行器的 `n.apply(d,e)` 包 try-catch。

### 3. 身份（cookie + localStorage）：日常纯协议刷新，**无需 Playwright**

签名绑定 cookie 里的 `UIFID_TEMP`，**签名与请求必须用同一份 cookie**。

- **日常刷新（推荐，纯协议，约 1~2 秒）**

  ```powershell
  .\iv8rs-lab\Scripts\python.exe douyin_identity.py --verify
  ```

  抖音只在「通过 acrawler 挑战的浏览器请求」上**首次**下发 `UIFID`/`ttwid`，所以**从零引导**需要一次浏览器；
  但只要手上有一个**曾经可用**的 cookie，就可以用 `curl_cffi`（伪造 Chrome 的 TLS/HTTP2 指纹）纯协议访问
  首页 + 用户页，服务端会续发一版新的 `ttwid / UIFID / web_sign_token`，合并后即为可用身份（实测 HTTP 200 / 17 条）。
  **首次引导之后，刷新全程不需要浏览器。**

- **首次引导 / 种子彻底失效时（一次性，约 4 秒）**

  ```powershell
  .\iv8rs-lab\Scripts\python.exe dump_fresh_env.py
  ```

  导出：

  ```
  cookie_fresh2.txt         ← 新鲜 cookie
  browser_ls_fresh.json     ← localStorage（含 EC 私钥/证书）
  ```

- ⚠️ **两条铁律**

  1. **绝不要用新 dump 覆盖 `browser_ls_fresh.json`**：实测新 localStorage 只要含 `xmst` 键，
     签名会整体失效（HTTP 200 但响应体为空）。`dump_fresh_env.py` 现已主动剔除 `xmst`。
  2. 刷新只动 cookie，不动 localStorage。

- `douyin_node_fetch.py` 已内置**自愈**：请求返回空时自动调用 `douyin_identity` 纯协议刷新 cookie 并重试一次。

### 4. 运行采集

```powershell
# 主页视频（纯协议，一条命令拿数据）
.\iv8rs-lab\Scripts\python.exe douyin_node_fetch.py

# 视频评论（可指定 aweme_id / 翻页数）
.\iv8rs-lab\Scripts\python.exe douyin_comments.py <aweme_id> --max-pages 5

# 备用：Playwright 浏览器内签名 + requests（Node 环境不可用时兜底）
python douyin_fetch.py
```

单独调用签名服务（任何语言都可调，stdout 输出单行 a_bogus）：

```powershell
node node_sign.js "device_platform=webapp&aid=6383&...&platform=PC"
```

### 5. 作为模块复用

```python
from douyin_sign import sign

# 任意接口：传入 path + query（不含 a_bogus），返回最终 URL 与请求头
final_url, headers = sign(
    path="/aweme/v1/web/comment/list/",
    query="aweme_id=xxx&cursor=0&count=20&item_type=0",
    referer="https://www.douyin.com/video/xxx",
)
```

---

## 三、脚本说明

| 脚本                   | 作用                                                                                    |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `node_sign.js`         | Node 真实 V8 签名服务：读 query，stdout 输出 a_bogus（约 12ms，纯同步）                 |
| `douyin_sign.py`       | 一站式签名模块 `sign(path, query, referer)`：串联 Node + iv8rs，返回最终 URL 与 headers |
| `douyin_node_fetch.py` | 主页视频采集生产入口：Node 签名 → iv8rs 补全 → requests 取数                            |
| `douyin_comments.py`   | 视频评论采集：复用同一签名链，自动翻页、去重、遇空页停止                                |
| `douyin_identity.py`   | **纯协议刷新身份 cookie**（curl_cffi，无浏览器，约 1~2s；`--verify` 顺带打接口验证）    |
| `douyin_fetch.py`      | 备用方案：Playwright 浏览器内生成签名 + requests 取数                                   |
| `dump_fresh_env.py`    | 一次性引导：Playwright 导出 cookie + localStorage（已自动剔除 `xmst`）                  |
| `xhr_shim.js`          | iv8rs 侧 XHR 包装（绕过其 XHR 原型不可扩展的限制）                                      |

更完整的逆向过程与踩坑记录见 `docs/iv8vsplaywright.md`（补环境引擎选型：iv8rs vs Playwright）与 `docs/node_v8.md`（Node 真实 V8 签名方案）。
