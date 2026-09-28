# 抖音主页视频采集 —— 纯协议方案完整教程（Node 真实 V8 签名版）


---

## 一、接口难在哪

### 1.1 响应不加密，请求要签名

抓包看 `/aweme/v1/web/aweme/post/` 的返回：**纯明文 JSON**，一个字节都没加密。
真正的门槛全在**请求侧**——URL 上必须带一个叫 **`a_bogus`** 的参数：

```
GET /aweme/v1/web/aweme/post/?device_platform=webapp&aid=6383&...&platform=PC
    &verifyFp=verify_xxx&fp=verify_xxx
    &a_bogus=xysnDe6wdp5jedKSYOGvSt%2Fl%2F...      ← 就是它
    &uifid=<160位hex>&timestamp=<unix秒>
```

实测结论（全部做过对照实验）：

| 参数                                         | 必需性      | 说明                                                    |
| -------------------------------------------- | ----------- | ------------------------------------------------------- |
| `a_bogus`                                    | ✅ **必需** | 去掉 → 返回空                                           |
| `uifid` / `timestamp`                        | ✅ 必需     | 缺了报 `Blocked by ArgusSecurityPlugin Uifid Not Found` |
| `x-secsdk-web-signature`（请求头）           | ✅ 必需     | 缺了报 `Signature Not Found`                            |
| `verifyFp` / `fp`                            | 🟡 建议带上 | 是签名明文的一部分，真实页面必带                        |
| cookie（含 UIFID_TEMP / s_v_web_id / ttwid） | ✅ 必需     | 缺了直接风控                                            |

### 1.2 a_bogus 是什么、怎么算的

CDP 断点跟栈确认的调用链（从业务代码到原生 XHR）：

```
routes-User-id-route.js（业务代码发起请求）
  → janus proxy → axios → dtrait-core
  → 20021.js（XHR.send 包装）
  → captcha/index.js
  → bdms_1.0.1.19_fix.js   ← ★ a_bogus 在这里诞生
  → sdk-glue.js → runtime_bundler_34.js
  → 原生 XHR.send（此时 URL 已带 a_bogus）
```

关键点：**bdms 是一个 JSVMP（JS 虚拟机字节码）**。整个 a_bogus 算法被编译成自定义字节码（`484e4f4a...` 开头），由内置的解释器逐条执行。静态搜索全部 8 个 JS 文件，**找不到 `a_bogus` 四个字母的明文**——参数名、算法、常量全在字节码里。

### 1.3 a_bogus 的签名明文（逆向出来的结构）

用 hook `String.prototype.charCodeAt` 抓到了签名原文（两端一致验证）：

```
<UIFID_TEMP 全值(160位hex)>_<unix时间戳>_<UA的MD5(32位hex)>_<完整query含verifyFp&fp>
```

也就是说 a_bogus 绑定：**cookie 里的 UIFID_TEMP + 时间戳 + User-Agent + 全部 query 参数**。
所以它**每次请求都要现场生成**，改任何一个参数都会失效。

---

## 二、为什么最后选了 Node.js 真实 V8

### 2.1 三条路线的实测结果

| 路线                                                | a_bogus 长度 | 服务端             | 结论        |
| --------------------------------------------------- | ------------ | ------------------ | ----------- |
| 真实 Chrome                                         | 184 / 188    | ✅ 200             | 基准        |
| **iv8rs 沙箱**（Rust V8 sandbox + JS polyfill DOM） | 192 / 196    | ❌ 200 空响应      | **被拒**    |
| **Node.js 真实 V8 + jsdom**                         | 192          | ✅ **200 + 17 条** | **✅ 采用** |
| Node.js + jsdom 默认 UA                             | 160          | ❌ 403             | UA 不对     |

### 2.2 一个重要的认知修正

我们曾用"同输入对照实验"锁定过一个铁证：**签名明文两端完全一致（516 字符），但输出长度不同**，当时推断"差异在引擎内部"。

Node 方案跑通后真相大白：**a_bogus 的输出长度本身就不固定**——

- jsdom 默认 UA（`jsdom/29.1.1`）→ 160
- 伪装成 Chrome/147 UA → 192
- 真实 Chrome → 184/188

**服务端并不校验"长度必须是 184"，它校验的是"a_bogus 的值与你声称的指纹（UA/cookie）是否自洽"。**
iv8rs 之所以被拒，不是"引擎算错"，而是 **iv8rs 的 JS polyfill 环境里某些底层对象行为与真实 V8 有细微差异，导致 VM 中间值不自洽**。Node 是货真价实的 V8，同样的字节码跑出来服务端就认。

> 一句话总结：**JSVMP 这种"字节码自解释"的方案，最怕的就是非标准引擎。想不重写算法，就给它一个真 V8。**

### 2.3 为什么不全用 Node、还要 iv8rs？

因为签名链有两段：

1. **a_bogus**（bdms 生成）→ Node 真实 V8 ✅
2. **uifid / timestamp / x-secsdk-web-signature**（`SDKRuntime.global.webSignUrl` 生成）→ 这段在 iv8rs 里已验证 100% 正确，且 iv8rs 的 `page_load_with_headers` 能直接注入 cookie/localStorage，写起来最顺手

两者组合 = 最短路径。**其实第 2 段也可以在 Node 里跑**（同样的 5 件套加载），如果想去掉 iv8rs 依赖，把 webSignUrl 部分也搬进 node_sign.js 即可——本文档附了思路。

---

## 三、文件清单与角色

```
douyin/
├── node_sign.js              ★ Node 签名服务：读 query，输出 a_bogus（12ms）
├── douyin_node_fetch.py      ★ 生产入口：三步串联
├── xhr_shim.js               iv8rs 用的 XHR 包装（Node 版已内置）
├── browser_ls_fresh.json     浏览器导出的 localStorage（含 EC 私钥/证书）
├── cookie_fresh2.txt         浏览器导出的新鲜 cookie（UIFID_TEMP 会话级）
├── webmssdk.js               底层 VM（_$webrt_1668687510）
└── recycle/
    ├── runtime_bundler_34.js   @byted/secsdk-strategy v1.0.40
    ├── sdk-glue.js             模块装配器（暴露 _SdkGlueInit）
    ├── bdms_fix.js             ★ bdms 1.0.1.19（a_bogus 主角，含2处兼容补丁）
    └── captcha_index.js        验证中心 SDK
└── aweme_node.json           最新采集结果（17条）
```

**bdms_fix.js 的两处补丁**（iv8rs 需要，Node/jsdom 下无害）：

1. 模块 394：`n[Symbol.toStringTag]="z"` 包 try-catch（core-js UA 检测在严格模式下对只读属性赋值会 throw）
2. VM 执行器 `n.apply(d,e)` 包 try-catch（防止个别 handler 在非标准环境抛错中断签名）

---

## 四、手把手：怎么跑起来

### 4.1 环境

```powershell
# Node 22 + jsdom（用国内镜像）
npm config set registry https://registry.npmmirror.com
npm i jsdom --no-audit --no-fund

# Python 3.13 + iv8rs + requests
uv venv iv8rs-lab
.\iv8rs-lab\Scripts\pip install ming-iv8-rs requests
```

### 4.2 拿新鲜 cookie + localStorage（一次性，或过期后重做）

用 Playwright 打开一次目标主页，导出：

```python
# dump_fresh_env.py 已有，核心逻辑：
cookies = await ctx.cookies()          # → cookie_fresh2.txt
ls = await pg.evaluate("() => {...}")  # → browser_ls_fresh.json
```

⚠️ **`UIFID_TEMP` 是会话级 cookie，SDK 会刷新它**。签名时用的值必须和你发请求时带的值一致。

### 4.3 跑生产脚本

```powershell
cd douyin
.\iv8rs-lab\Scripts\python.exe douyin_node_fetch.py
```

输出：

```
[1/3] Node.js 真实V8 生成 a_bogus ...
    a_bogus len=192
[2/3] iv8rs webSignUrl 补全 uifid/timestamp/x-secsdk-web-signature ...
[3/3] requests 请求 ...
HTTP 200 len 1344683
status_code: 0 aweme: 17
  1. 7680843869864414470 | 1万平米，超大充气城堡！ | 赞29688 | 评544
  2. 7680081231240908038 | 如果能看到未来价值，你会怎么做？ | 赞63474 | 评860
  ...（17条）
saved aweme_node.json
```

### 4.4 单独调用签名服务

```powershell
node node_sign.js "device_platform=webapp&aid=6383&...&platform=PC"
# stdout 直接输出 a_bogus 单行，方便任何语言调用
```

---

## 五、node_sign.js 内部拆解

整个脚本就干 5 件事，**全程同步、12ms 出结果、不需要事件循环**：

```js
// 1. 造一个假浏览器窗口（jsdom = 真V8 + 真DOM实现）
const dom = new JSDOM("<html><body></body></html>", {
  url: "https://www.douyin.com/user/xxx",
});

// 2. 注入"身份"：localStorage（含EC私钥）+ cookie（含UIFID_TEMP）
win.localStorage.setItem(k, v);
win.document.cookie = "UIFID_TEMP=1c8b...; path=/";

// 3. 伪装指纹（★最关键的一步）
//    jsdom 默认 UA 是 "jsdom/29.1.1"，a_bogus 会算成 160 位被拒
//    必须改成完整 Chrome UA + 1920x1080 屏幕
Object.defineProperty(win.navigator, "userAgent", { get: () => CHROME_UA });

// 4. 换掉 XMLHttpRequest（假壳，send() 什么都不做）
//    因为签名发生在 XHR.open/send 被 secsdk 包装的瞬间，不需要真发网络请求
win.XMLHttpRequest = XHRShim;

// 5. 按真实页面顺序加载 5 个安全脚本，然后：
win.eval(
  "_SdkGlueInit({aid:6383, bdms:{paths:['/aweme/v1/web/aweme/post/']}})"
); // 装配
win.eval("x.open('GET', url); x.send()"); // 触发 → bdms 的 VM 跑起来 → URL 被 append 上 a_bogus
// hook URLSearchParams.append 抓到 a_bogus 值
```

**为什么 `send()` 是空的也能签出来？**
因为 bdms 的 hook 逻辑是：`XHR.send` 被调用时 → 解析 URL → 构造签名明文 → VM 计算 → `URLSearchParams.append('a_bogus', 值)`。整个签名过程是**同步的纯计算**，不依赖网络返回。

---

## 六、踩坑记录（都是真金白银的时间）

| 坑                                           | 现象                                                                        | 解法                                   |
| -------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------- |
| iv8rs 的 `Object.prototype` 被 freeze        | bdms 模块 394 抛 `Cannot assign to read only property 'Symbol.toStringTag'` | 补丁包 try-catch                       |
| iv8rs 的 `XMLHttpRequest.prototype` 不可扩展 | `object is not extensible`                                                  | 用包装类整体替换                       |
| iv8rs `Date.now()` 冻结在 2024-01-01         | 时间戳不对                                                                  | `performance.timeOrigin` + 重建 `Date` |
| jsdom 默认 UA                                | a_bogus=160 被拒                                                            | 伪装完整 Chrome UA                     |
| URL 缺 `uifid`                               | 403 `Uifid Not Found`                                                       | webSignUrl 自动补                      |
| 缺 `x-secsdk-web-signature` 头               | 403 `Signature Not Found`                                                   | webSignUrl 返回的 headers 带上         |
| 旧 cookie                                    | 403 `ArgusSecurityPlugin` 风控                                              | 用新鲜 cookie                          |
| npm 官方源超时                               | 装不上 jsdom                                                                | 换 npmmirror 镜像                      |
| Python 里建了 `base64.py`                    | 标准库被覆盖，`import base64` 炸                                            | 删掉/改名（别用标准库名建文件！）      |

---

## 七、进阶：去掉 iv8rs 依赖（可选）

`webSignUrl` 本质也是 JS（runtime_bundler + sdk-glue 里的 `SDKRuntime.global.webSignUrl`），完全可以搬进 Node：

```js
// 在 node_sign.js 的第 5 步之后加：
win.eval(
  "window.__sign=JSON.stringify(SDKRuntime.global.webSignUrl('" +
    baseUrl +
    "'))"
);
const { url, headers } = JSON.parse(win.eval("window.__sign"));
// url 已含 uifid/timestamp，headers 里带 x-secsdk-web-signature
```

这样整条链就是 **纯 Node**，Python 只负责最后一步 requests（甚至用 Node fetch 也行）。

---

## 八、交付物汇总

| 交付物                 | 说明                                                                                     |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| `douyin_node_fetch.py` | ★ 生产入口，一条命令拿 17 条视频 JSON                                                    |
| `node_sign.js`         | ★ 独立签名服务，任何语言可调用                                                           |
| `aweme_node.json`      | 最新采集结果（17 条，含 desc/点赞/评论/收藏/分享数）                                     |
| `douyin_fetch.py`      | 备用：Playwright 混合方案（浏览器签名+requests）                                         |
| `bdms_vm.json` 等      | bdms JSVMP 字节码完整 dump（Z 字符串池 1001 项/handler 表 796 项/原始字节码 86939 字节） |
| 本文档                 | 全流程逆向分析 + 踩坑记录                                                                |

**核心结论一句话**：a_bogus 的算法在 bdms 的 JSVMP 字节码里，不重写算法的唯一出路是"给它一个真 V8"——Node.js + jsdom + 正确的指纹伪装，就是那条出路。
