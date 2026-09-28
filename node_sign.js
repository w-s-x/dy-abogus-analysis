// node_sign.js —— Node 真实 V8 签名服务：生成 a_bogus
// 用法: node node_sign.js <query>   输出: a_bogus 值(仅一行)
const fs = require('fs');
const { JSDOM } = require('jsdom');

const R = 'recycle/';
const files = {
  runtime: R + 'runtime_bundler_34.js',
  webmssdk: 'webmssdk.js',
  glue: R + 'sdk-glue.js',
  bdms: R + 'bdms_fix.js',
  captcha: R + 'captcha_index.js',
};
const COOKIE = fs.readFileSync('cookie_fresh2.txt', 'utf8').trim();
const LS = JSON.parse(fs.readFileSync('browser_ls_fresh.json', 'utf8'));
const SEC = 'MS4wLjABAAAAMu1bTpiU1vjKek2GJLDzvYiho9DBnWmUqsXjzAQ7a7Y';
const Q = process.argv[2] || ('device_platform=webapp&aid=6383&channel=channel_pc_web&sec_user_id=' + SEC +
  '&max_cursor=0&count=18&from_user_page=1&version_code=290100&platform=PC');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'https://www.douyin.com/user/' + SEC,
  referrer: 'https://www.douyin.com/', pretendToBeVisual: true, runScripts: 'outside-only',
});
const win = dom.window;
try { for (const [k, v] of Object.entries(LS)) win.localStorage.setItem(k, v); } catch (e) {}
try { for (const kv of COOKIE.split('; ')) { if (kv.includes('=')) win.document.cookie = kv + '; path=/'; } } catch (e) {}

class XHRShim {
  constructor(){ this.readyState=0; this._h={}; this.onload=null; this.onreadystatechange=null; this.onerror=null; }
  open(m,u){ this.method=m; this.url=u; this.readyState=1; }
  setRequestHeader(k,v){ (this._h[k]=this._h[k]||[]).push(v); }
  addEventListener(t,f){ const p='on'+t; const prev=this[p]; this[p]=function(e){ try{f.call(this,e);}catch(_){} if(typeof prev==='function') try{prev.call(this,e);}catch(_){} }; }
  removeEventListener(){}
  dispatchEvent(){ return true; }
  getAllResponseHeaders(){ return ''; }
  send(){}
  abort(){}
}
XHRShim.UNSENT=0; XHRShim.OPENED=1; XHRShim.HEADERS_RECEIVED=2; XHRShim.LOADING=3; XHRShim.DONE=4;
win.XMLHttpRequest = XHRShim;

try { Object.defineProperty(win.performance, 'timeOrigin', { value: Date.now(), configurable: true }); } catch(e){}

const FAKE_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
try {
  const D = (o, k, v) => Object.defineProperty(o, k, { get: () => v, configurable: true });
  D(win.navigator, 'userAgent', FAKE_UA);
  D(win.navigator, 'appVersion', FAKE_UA.replace('Mozilla/', ''));
  D(win.navigator, 'platform', 'Win32');
  D(win.navigator, 'vendor', 'Google Inc.');
  D(win.screen, 'width', 1920); D(win.screen, 'height', 1080);
  D(win.screen, 'availWidth', 1920); D(win.screen, 'availHeight', 1040);
  D(win.screen, 'colorDepth', 24); D(win.screen, 'pixelDepth', 24);
  D(win, 'innerWidth', 1476); D(win, 'innerHeight', 1040);
  D(win, 'outerWidth', 1920); D(win, 'outerHeight', 1080);
  D(win, 'devicePixelRatio', 1);
} catch (e) {}

win.eval("window._sdkGlueVersionMap={sdkGlueVersion:'1.0.0.64-fix.01',bdmsVersion:'1.0.1.19-fix.01',captchaVersion:'4.0.10'};");
for (const k of ['runtime','webmssdk','glue','bdms','captcha']) {
  try { win.eval(fs.readFileSync(files[k], 'utf8')); } catch (e) {}
}
win.eval("window.__full=null; var _a=URLSearchParams.prototype.append; URLSearchParams.prototype.append=function(k,v){ if(String(k)==='a_bogus') window.__full=String(v); return _a.apply(this,arguments); };");
try { win.eval("_SdkGlueInit({ aid:6383, mssdk:{aid:6383,paths:[],pageId:1}, bdms:{paths:['/aweme/v1/web/aweme/post/'],boe:false} });"); } catch(e){}
try { win.eval(`(function(){ var x=new XMLHttpRequest(); x.open('GET','https://www.douyin.com/aweme/v1/web/aweme/post/?${Q}'); x.send(); })()`); } catch(e){}
const ab = win.eval("String(window.__full||'')");
process.stdout.write(ab);
process.exit(0);
