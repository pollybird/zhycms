/**
 * CSRF 同步 Token 自动注入（v3.1.1，GitCode issue #1 H2）。
 *
 * 约定：页面 <head> 中需有 <meta name="csrf-token" content="{{ csrf_token() }}">。
 * 本脚本在 document 捕获阶段监听 submit 事件：表单内没有 _csrf_token 字段时，
 * 自动补一个 hidden input（值取 meta）。异步 fetch/XHR 请求请自行携带
 * X-CSRF-Token 请求头（值同 meta）。
 */
(function () {
  'use strict';

  function readToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }

  function injectToken(f) {
    if (!f || f.nodeName !== 'FORM') return;
    if (f.querySelector('input[name="_csrf_token"], input[name="csrf_token"]')) return;
    var token = readToken();
    if (!token) return;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = '_csrf_token';
    input.value = token;
    f.appendChild(input);
  }

  document.addEventListener('submit', function (e) {
    injectToken(e.target);
  }, true);

  // jQuery 的 .submit() / form.submit() 不会派发原生 submit 事件，捕获监听
  // 无法生效。页面加载完成后为所有已存在的表单预注入 Token，覆盖
  // 「脚本提交表单」的场景（如批量操作、下拉框 onchange 自动提交）。
  document.addEventListener('DOMContentLoaded', function () {
    var forms = document.forms;
    for (var i = 0; i < forms.length; i++) injectToken(forms[i]);
  });

  // 便捷读取：window.csrfToken 供手写 fetch 使用
  try {
    Object.defineProperty(window, 'csrfToken', { get: readToken });
  } catch (err) { /* ignore */ }

  // jQuery $.post/$.ajax 全局附加 X-CSRF-Token（jQuery 可能晚于本脚本加载，
  // 故在 DOMContentLoaded 后注册）
  document.addEventListener('DOMContentLoaded', function () {
    if (window.jQuery) {
      window.jQuery.ajaxSetup({
        beforeSend: function (xhr) {
          var t = readToken();
          if (t) xhr.setRequestHeader('X-CSRF-Token', t);
        }
      });
    }
  });
})();
