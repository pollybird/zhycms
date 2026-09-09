# -*- coding: utf-8 -*-
"""一键翻译插件：后台编辑页资源注入。

通过 Jinja 全局函数 ``auto_translate_assets()`` 在后台 base.html 输出一段
引导脚本（插件禁用时由核心守卫返回空字符串）。脚本职责：

1. 拦截 CKEditor5 ``ClassicEditor.create``，建立 textarea 元素 → 编辑器实例的
   弱引用映射（供一键翻译读写富文本内容）；
2. 自动识别编辑页多语言 Tab（``#i18n-tabs``），在每个非默认语言面板顶部插入
   「一键翻译」按钮；
3. 点击后按通用命名规则（源字段 ``name="title"`` → 译文字段
   ``name="title_en"``）收集默认语言内容，调用插件翻译 API，回填译文，
   富文本通过 CKEditor ``setData`` 写入、普通字段直接写 value。

不依赖各编辑页模板的特定结构，文章/栏目/碎片/产品/表单/招聘/友链等页面
只要遵循多语言 Tab 命名约定即自动生效。
"""
from flask import url_for
from markupsafe import Markup


def render_assets():
    """返回注入后台页面的 <script> 片段（仅插件启用时被调用）。"""
    api_url = url_for('admin.auto_translate_translate')
    return Markup(_JS_TEMPLATE.replace('__API_URL__', api_url))


# 引导脚本（纯原生 JS，无额外依赖；注意花括号不与 Jinja 冲突，此处为普通字符串）
_JS_TEMPLATE = r"""
<script>
(function () {
  'use strict';

  /* ---------- CKEditor5 实例注册表 ---------- */
  window.__ck5 = window.__ck5 || { editors: new WeakMap() };
  function __wrapCK(CK) {
    try {
      if (!CK || !CK.ClassicEditor || !CK.ClassicEditor.create || CK.ClassicEditor.__atWrapped) return;
      var origCreate = CK.ClassicEditor.create;
      CK.ClassicEditor.create = function (el, config) {
        var p = origCreate.apply(this, arguments);
        try {
          if (el && p && typeof p.then === 'function') {
            p.then(function (editor) { window.__ck5.editors.set(el, editor); });
          }
        } catch (e) {}
        return p;
      };
      CK.ClassicEditor.__atWrapped = true;
    } catch (e) {}
  }
  // ckeditor.js 在本脚本之后加载并赋值 window.CKEDITOR：用访问器拦截一次
  var __ckHolder;
  try {
    Object.defineProperty(window, 'CKEDITOR', {
      configurable: true,
      get: function () { return __ckHolder; },
      set: function (v) { __ckHolder = v; __wrapCK(v); }
    });
  } catch (e) { /* 若已存在则直接包裹 */ }
  __wrapCK(window.CKEDITOR);

  /* ---------- 字段读写（自动识别 CKEditor 富文本） ---------- */
  function getEditor(el) {
    try { return window.__ck5.editors.get(el); } catch (e) { return null; }
  }
  function readField(el) {
    if (!el) return '';
    if (el.tagName === 'TEXTAREA') {
      var ed = getEditor(el);
      if (ed) { try { return ed.getData(); } catch (e) {} }
    }
    return el.value || '';
  }
  function writeField(el, val) {
    if (!el) return;
    if (el.tagName === 'TEXTAREA') {
      var ed = getEditor(el);
      if (ed) { try { ed.setData(val); el.value = val; return; } catch (e) {} }
    }
    el.value = val;
    try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
    try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  // 富文本字段判定：绑定了 CKEditor 实例，或类名含 richtext（兼容 page-richtext /
  // i18n-value-richtext 等各页面命名）
  function isHtmlField(el) {
    if (!el || el.tagName !== 'TEXTAREA') return false;
    if (getEditor(el)) return true;
    return /richtext/i.test(el.className || '');
  }

  var API_URL = '__API_URL__';

  function translatePane(pane) {
    var loc = (pane.id || '').replace(/^i18n-/, '');
    if (!loc) return;
    var form = pane.closest('form') || document.querySelector('form');
    if (!form) return;
    var btn = pane.querySelector('.auto-translate-btn');
    var status = pane.querySelector('.auto-translate-status');

    // 收集本面板的译文字段 → 对应默认语言源字段
    var targets = pane.querySelectorAll('input[name], textarea[name]');
    var fields = {}, htmlFields = [], jobs = [];
    targets.forEach(function (tel) {
      var name = tel.getAttribute('name') || '';
      var suffix = '_' + loc;
      if (name.length <= suffix.length || name.slice(-suffix.length) !== suffix) return;
      var base = name.slice(0, name.length - suffix.length);
      var sel = form.querySelector('[name="' + base + '"]') ||
                document.querySelector('[name="' + base + '"]');
      if (!sel) return;
      var text = readField(sel);
      if (!text || !text.replace(/<[^>]*>/g, '').trim()) return;  // 源内容为空则跳过
      fields[base] = text;
      if (isHtmlField(tel) || isHtmlField(sel)) htmlFields.push(base);
      jobs.push({ tel: tel, base: base });
    });

    if (!Object.keys(fields).length) {
      if (status) { status.textContent = '请先填写默认语言内容'; status.className = 'auto-translate-status ml-2 text-danger'; }
      return;
    }
    // 译文已有内容时二次确认，避免误覆盖
    var hasContent = jobs.some(function (j) {
      return readField(j.tel).replace(/<[^>]*>/g, '').trim();
    });
    if (hasContent && !window.confirm('当前 ' + loc.toUpperCase() + ' 标签页已有内容，一键翻译将覆盖现有译文，是否继续？')) {
      return;
    }

    if (btn) { btn.disabled = true; btn.classList.add('disabled'); }
    if (status) { status.textContent = '翻译中，请稍候……'; status.className = 'auto-translate-status ml-2 text-muted'; }

    fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ target: loc, fields: fields, html_fields: htmlFields })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res || !res.ok) { throw new Error((res && res.error) || '翻译失败'); }
      var count = 0;
      jobs.forEach(function (j) {
        if (res.data && typeof res.data[j.base] === 'string') {
          writeField(j.tel, res.data[j.base]);
          count++;
        }
      });
      if (status) {
        status.textContent = '翻译完成，已填充 ' + count + ' 个字段，请检查后保存';
        status.className = 'auto-translate-status ml-2 text-success';
      }
    }).catch(function (err) {
      if (status) { status.textContent = '翻译失败：' + err.message; status.className = 'auto-translate-status ml-2 text-danger'; }
    }).finally(function () {
      if (btn) { btn.disabled = false; btn.classList.remove('disabled'); }
    });
  }

  function injectButtons() {
    var panes = document.querySelectorAll('div.tab-pane[id^="i18n-"]');
    panes.forEach(function (pane) {
      if (pane.querySelector('.auto-translate-btn')) return;
      var loc = pane.id.replace(/^i18n-/, '');
      var bar = document.createElement('div');
      bar.className = 'mb-2 clearfix';
      bar.innerHTML =
        '<button type="button" class="btn btn-sm btn-outline-primary float-right auto-translate-btn">' +
        '<i class="fas fa-language"></i> 一键翻译为 ' + escapeHtml(loc.toUpperCase()) +
        '</button><span class="auto-translate-status float-right text-sm mr-2 pt-1" style="line-height:30px;"></span>';
      pane.insertBefore(bar, pane.firstChild);
      bar.querySelector('.auto-translate-btn').addEventListener('click', function () { translatePane(pane); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectButtons);
  } else {
    injectButtons();
  }
})();
</script>
"""
