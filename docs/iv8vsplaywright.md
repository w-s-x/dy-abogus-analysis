# 抖音主页视频采集 —— 纯协议逆向 完整教程

> 目标：采集 `https://www.douyin.com/user/{sec_user_id}` 主页视频列表，
> 拿到 `/aweme/v1/web/aweme/post/` 接口返回的明文 JSON（`aweme_list`）。

---

## 一、整体分析结论

| 项 | 结论 |
|---|---|
| 响应加密 | **无**，直接是明文 JSON |
| 请求门槛 | 唯一门槛是 **`a_bogus`** 签名（query 参数） |
| `x-secsdk-web-signature` | 非必需（去掉仍 200），但真实页面会带 |
| `a_bogus` 必需性 | **必需**（去掉返回空） |
| `a_bogus` 绑定维度 | query + cookie + user-agent + 时间戳（每次现场生成，不可复用） |
| `a_bogus` 生成者 | **`bdms_1.0.1.19_fix.js`**（JSVMP 字节码，在 `XHR.send` 时生成） |
| 关键签名链 | `bdms` 生成 a_bogus → `SDKRuntime.global.webSignUrl()` 补 `uifid`/`timestamp`/`x-secsdk-web-signature` |

### 真实页面完整签名 URL 结构
```
/aweme/v1/web/aweme/post/?<业务query>
  &a_bogus=<bdms生成>
  &verifyFp=verify_xxx&fp=verify_xxx
  &uifid=<环境>
  &timestamp=<秒>
  &x-secsdk-web-signature=<secsdk生成>
```
- **a_bogus 的签名输入 = 业务 query**（verifyFp/fp 在其后 append，不参与 a_bogus）
- **请求 UA 必须与生成 a_bogus 时的 `navigator.userAgent` 一致**（否则服务端拒绝 → 返回空/403）

---

## 二、方案选型

- **混合方案（生产可用）**：Playwright 打开主页加载 secsdk → 页面内发 XHR（secsdk 自动补 a_bogus）→ 截获签名 URL → requests 复用 cookie 发送。**→ `douyin_fetch.py`，稳定 20/17 条**
- **纯 iv8rs 方案（攻坚中）**：用 `ming_iv8_rs`（iv8rs）在无浏览器环境复现 secsdk，本地生成 a_bogus。

---

## 三、纯 iv8rs 方案：环境搭建与关键补丁

### 3.1 需要下载的 secsdk 五件套（按真实加载顺序）
```
1. runtime_bundler_34.js   策略引擎    https://lf-security.bytegoofy.com/obj/security-secsdk-gray/runtime_bundler_34.js
2. webmssdk.es5.js         1.0.0.20    https://lf-c-flwb.bytetos.com/obj/rc-client-security/c-webmssdk/1.0.0.20/webmssdk.es5.js
3. sdk-glue.js             1.0.0.64    https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/glue/1.0.0.64-fix.01/sdk-glue.js
4. bdms_1.0.1.19_fix.js    1.0.1.19    https://p-pc-weboff.byteimg.com/tos-cn-i-9r5gewecjs/bdms_1.0.1.19_fix.js
5. captcha/index.js        4.0.28      https://lf-rc1.yhgfb-cn-static.com/obj/rc-verifycenter/sec_sdk_build/4.0.28/captcha/index.js
```

### 3.2 运行 iv8rs 必须的 4 个补丁

1. **`bdms_fix.js` 第 7025 行**：`n.apply(d,e)` 在 iv8rs 严格模式下会崩，需 try 包裹（见 `recycle/bdms_fix.js`）。

2. **XHR polyfill（最关键）**：iv8rs 的 `XMLHttpRequest.prototype` **不可扩展**，且原生 `addEventListener` 直接调用报 `Illegal invocation`。解决：**替换 `window.XMLHttpRequest` 为包装类**，给实例注入 `addEventListener/removeEventListener/dispatchEvent`（见 `xhr_shim.js`）。

3. **时间修复**：iv8rs 的 `Date.now()/performance.timeOrigin` 固定为 2024-01-01，需覆盖为真实时间：
   ```js
   Object.defineProperty(performance,'timeOrigin',{value: RealNow - performance.now(), configurable:true});
   // 并重建 Date
   ```

4. **注入 localStorage**：从真实浏览器导出的 localStorage（含 `security-sdk/s_sdk_crypt_sdk` 等）注入 iv8rs。

### 3.3 激活 bdms
```js
_SdkGlueInit({ aid: 6383, mssdk:{aid:6383,paths:[],pageId:1},
               bdms:{ paths:['/aweme/v1/web/aweme/post/'], boe:false } });
```

### 3.4 生成 a_bogus + 补全签名（核心代码）
```js
// 1) 触发 bdms 生成 a_bogus
const x = new XMLHttpRequest();
x.open('GET','https://www.douyin.com/aweme/v1/web/aweme/post/?'+query);
x.send();     // bdms 拦截 send，把 a_bogus append 到 URL

// 2) 用 webSignUrl 补 uifid/timestamp/x-secsdk-web-signature
const url = 'https://www.douyin.com/aweme/v1/web/aweme/post/?'+query+'&a_bogus='+a_bogus;
const signed = SDKRuntime.global.webSignUrl(url);
// signed.url 即最终可发送 URL
```

### 3.5 用 requests 发送
```python
requests.get(signed_url, headers={
    "user-agent": <必须等于 iv8rs 的 navigator.userAgent，即 Chrome/147>,
    "cookie": <cookie.txt>,
    ...})
```

---

## 四、当前状态与已知差距

### ✅ 已打通
- secsdk 五件套在 iv8rs 完整加载
- bdms 挂载并**成功生成 a_bogus**（192~196 字符）
- `SDKRuntime.global.webSignUrl` 正确补全签名链

### ✅ 决定性验证（除 a_bogus 外全通）
> **用浏览器生成的 a_bogus + iv8rs 的 `webSignUrl` 签名 + requests(UA147 + cookie.txt)**
> → **HTTP 200 / status_code 0 / 17 条 aweme** ✅

### ⚠️ 唯一差距
- iv8rs 的 bdms 生成的 a_bogus **长度 192/196**，真实 Chrome 为 **184/188**，**恒定差 ~6 字节**
- **已排除**：时间、随机数、cookie、localStorage、环境指纹、mssdk 网络、atob/btoa 编码
- **根因**：抖音 secsdk 全套（webmssdk / runtime_bundler / bdms）**均为 JSVMP**，a_bogus 算法在 VM 字节码中，输入经 VM 栈传递；**iv8rs 的 DOM 是 Rust/JS polyfill 实现**，与真实 Chrome 在 URL 解析等深层细节不一致（证据：浏览器 bdms 处理的是**相对路径** `/aweme/...`，iv8rs 处理的是**完整 URL** `https://www.douyin.com/aweme/...`，差 `https:` = 6 字节，正好对应 a_bogus 的 6 字节差；URL 补全点位于 `runtime_bundler_34.js:17:111858` 的 VM 内）。

---

## 五、关键脚本清单

| 文件 | 作用 |
|---|---|
| `douyin_fetch.py` | **生产可用**：混合方案（浏览器签名 + requests 取数） |
| `final_iv8rs3.py` | 纯 iv8rs：bdms 生成 a_bogus + webSignUrl 补全 + requests |
| `diagnose_sign.py` | 分诊：浏览器 a_bogus + iv8rs webSignUrl → 200（铁证） |
| `xhr_shim.js` | iv8rs 用的 XHR polyfill |
| `recycle/bdms_fix.js` | bdms 格式化+插桩版 |
| `browser_ls.json` | 浏览器 localStorage 导出 |
| `cookie.txt` | 完整 cookie |

---

## 六、数据输出

`aweme_post_latest.json` / `aweme_iv8rs.json` 为接口原始 JSON，含：
`aweme_id` / `desc` / `statistics`(点赞/评论/收藏/分享) / `video` / `author` 等。
