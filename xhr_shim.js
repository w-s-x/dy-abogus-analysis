(function(){
  var _Orig = window.XMLHttpRequest;
  if (!_Orig) return;
  function Wrap(){
    var x = new _Orig();
    var listeners = {};
    x.addEventListener = function(type, fn){
      (listeners[type] = listeners[type] || []).push(fn);
      var prop = 'on' + type;
      if (!x['__bridged_' + type]) {
        x['__bridged_' + type] = true;
        var prev = x[prop];
        var bridge = function(ev){
          var arr = listeners[type] || [];
          for (var i=0;i<arr.length;i++){ try{ arr[i].call(x, ev); }catch(e){} }
          if (typeof prev === 'function') { try{ prev.call(x, ev); }catch(e){} }
        };
        try { x[prop] = bridge; } catch(e){}
      }
      return undefined;
    };
    x.removeEventListener = function(type, fn){
      if (listeners[type]){ var i=listeners[type].indexOf(fn); if(i>=0) listeners[type].splice(i,1); }
    };
    x.dispatchEvent = function(ev){ return true; };
    return x;
  }
  Wrap.prototype = _Orig.prototype;
  try { Wrap.UNSENT=_Orig.UNSENT; Wrap.OPENED=_Orig.OPENED; Wrap.HEADERS_RECEIVED=_Orig.HEADERS_RECEIVED; Wrap.LOADING=_Orig.LOADING; Wrap.DONE=_Orig.DONE; } catch(e){}
  window.XMLHttpRequest = Wrap;
})();
