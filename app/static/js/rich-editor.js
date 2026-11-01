/**
 * 后台富文本编辑器共享组件（v3.1.5）
 *
 * CKEditor5 富文本 / Markdown 双模式编辑：
 * - 顶部「富文本 | Markdown」分段控件一键切换（切向 Markdown 时二次确认，提示有损）
 * - Markdown 模式实时预览（marked，300ms 防抖）、插入图片、全屏
 * - CKEditor 按需加载：初始为 Markdown 模式时不加载 ckeditor.js（约 1MB）
 *
 * 表单契约（与服务端 app/utils/markdown_render.py 的 apply_editor_form 对应）：
 * - 原 textarea（如 name="content"）始终提交 HTML（Markdown 模式下提交前用 marked 渲染回填，
 *   服务端仍以其配套的 *_md 原文为准重新渲染，此处仅为兜底）；
 * - 隐藏域 {field}_format 提交 'html' / 'markdown'；
 * - Markdown 原文 textarea（name="{field}_md"）提交 Markdown 源码。
 *
 * 用法：
 *   RichEditor.configure({ckUrl: '...', ckLangUrl: '...', i18n: {...}});
 *   const inst = RichEditor.init({textarea: el, ckConfig: {...}, uploadUrl: '...'});
 * textarea 需带 data 属性：data-md-field（Markdown 原文 textarea 的 name）、
 * data-format-field（格式隐藏域的 name）、data-mode（初始模式 ckeditor/markdown）。
 * 纯 CKEditor 字段（无 Markdown 列的自定义字段）用 RichEditor.loadCk() 后自行初始化。
 */
(function () {
  'use strict';

  var _cfg = {
    ckUrl: null,
    ckLangUrl: null,
    i18n: {
      richText: '富文本',
      preview: '预览',
      insertImage: '插入图片',
      fullscreen: '全屏',
      exitFullscreen: '退出全屏',
      confirmToMarkdown: '复杂排版（表格样式、字体字号、对齐等）在 Markdown 模式下可能丢失，建议切换后检查再保存。是否继续？',
      uploading: '上传中…',
      uploadFailed: '图片上传失败'
    }
  };

  function configure(opts) {
    if (!opts) return;
    if (opts.ckUrl) _cfg.ckUrl = opts.ckUrl;
    if (opts.ckLangUrl) _cfg.ckLangUrl = opts.ckLangUrl;
    if (opts.i18n) {
      for (var k in opts.i18n) {
        if (Object.prototype.hasOwnProperty.call(opts.i18n, k)) _cfg.i18n[k] = opts.i18n[k];
      }
    }
  }

  // ---------- 依赖加载 ----------

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('加载脚本失败: ' + src)); };
      document.head.appendChild(s);
    });
  }

  var _ckPromise = null;

  /** 按需加载 CKEditor（含中文语言包），全页共享同一个 Promise。 */
  function loadCk() {
    if (window.CKEDITOR && window.CKEDITOR.ClassicEditor) return Promise.resolve();
    if (_ckPromise) return _ckPromise;
    _ckPromise = loadScript(_cfg.ckUrl).then(function () {
      if (_cfg.ckLangUrl) return loadScript(_cfg.ckLangUrl);
    }).then(function () {
      if (!window.CKEDITOR || !window.CKEDITOR.ClassicEditor) {
        throw new Error('CKEditor 加载失败');
      }
    });
    return _ckPromise;
  }

  /** Markdown 前端依赖（marked / TurndownService）是否就绪。 */
  function mdLibReady() {
    return typeof window.marked !== 'undefined' && typeof window.TurndownService !== 'undefined';
  }

  function mdToHtml(md) {
    if (!md) return '';
    // breaks:true 与服务端 nl2br 扩展行为对齐
    return window.marked.parse(md, { breaks: true });
  }

  var _turndown = null;

  function htmlToMd(html) {
    if (!html) return '';
    if (!_turndown) {
      _turndown = new window.TurndownService({
        headingStyle: 'atx',
        codeBlockStyle: 'fenced',
        bulletListMarker: '-'
      });
    }
    return _turndown.turndown(html);
  }

  // ---------- 样式（注入一次） ----------

  var _styleInjected = false;

  function injectStyle() {
    if (_styleInjected) return;
    _styleInjected = true;
    var css =
      '.rich-editor .re-toolbar{display:flex;justify-content:space-between;align-items:center;' +
      'flex-wrap:wrap;gap:.4rem;padding:.35rem 0 .45rem}' +
      '.rich-editor .re-md-body{display:flex;border:1px solid #ced4da;border-radius:.25rem;' +
      'overflow:hidden;background:#fff}' +
      '.rich-editor textarea.re-md-input{font-family:SFMono-Regular,Menlo,Consolas,"Courier New",monospace;' +
      'font-size:14px;line-height:1.7;border:0;border-radius:0;resize:vertical;flex:1 1 50%;padding:.75rem}' +
      '.rich-editor .re-preview{flex:1 1 50%;border-left:1px solid #e9ecef;padding:.75rem 1rem;' +
      'overflow:auto;font-size:15px;line-height:1.8;word-break:break-word}' +
      '.rich-editor .re-preview img{max-width:100%}' +
      '.rich-editor .re-preview>:first-child{margin-top:0}' +
      '.rich-editor .re-md-body.re-no-preview .re-preview{display:none}' +
      '.rich-editor .re-md-body.re-no-preview textarea.re-md-input{flex-basis:100%}' +
      '.rich-editor.re-fullscreen{position:fixed;inset:0;z-index:1060;background:#fff;padding:1rem;' +
      'display:flex;flex-direction:column;overflow:auto}' +
      '.rich-editor.re-fullscreen .re-md-body{flex:1;min-height:0}' +
      '.rich-editor.re-fullscreen textarea.re-md-input,.rich-editor.re-fullscreen .re-preview{height:100%}' +
      '@media (max-width:991.98px){.rich-editor .re-md-body{flex-direction:column}' +
      '.rich-editor .re-preview{border-left:0;border-top:1px solid #e9ecef}}';
    var style = document.createElement('style');
    style.type = 'text/css';
    style.appendChild(document.createTextNode(css));
    document.head.appendChild(style);
  }

  // ---------- 实例 ----------

  var instances = [];

  /**
   * @param {Object} opts
   *   textarea      {HTMLElement|string} 原 textarea（HTML 载体，必填）
   *   ckConfig      {Object}   CKEditor 配置（原样透传 ClassicEditor.create）
   *   uploadUrl     {string}   图片上传地址（复用 admin.upload_file）
   *   uploadType    {string}   上传子目录（type 参数，如 article/column/fragment）
   *   minHeight     {number}   Markdown 编辑区最小高度 px（默认 600）
   */
  function init(opts) {
    var inst = new RichEditorInstance(opts);
    instances.push(inst);
    return inst;
  }

  function RichEditorInstance(opts) {
    injectStyle();
    this.textarea = typeof opts.textarea === 'string'
      ? document.querySelector(opts.textarea) : opts.textarea;
    if (!this.textarea) throw new Error('RichEditor: textarea 不存在');
    this.ckConfig = opts.ckConfig || {};
    this.uploadUrl = opts.uploadUrl || '';
    this.uploadType = opts.uploadType || 'common';
    this.minHeight = opts.minHeight || 600;

    var form = this.textarea.form;
    var mdName = this.textarea.getAttribute('data-md-field');
    var fmtName = this.textarea.getAttribute('data-format-field');
    this.mdTextarea = mdName && form ? form.querySelector('textarea[name="' + mdName + '"]') : null;
    this.formatInput = fmtName && form ? form.querySelector('input[name="' + fmtName + '"]') : null;

    var mode = this.textarea.getAttribute('data-mode') === 'markdown' ? 'markdown' : 'ckeditor';
    // Markdown 前端依赖缺失时降级为富文本，保证可用
    if (mode === 'markdown' && !mdLibReady()) {
      window.console.error('RichEditor: marked/turndown 未加载，降级为富文本模式');
      mode = 'ckeditor';
    }
    this.mode = mode;
    this.editor = null;        // CKEditor 实例（按需创建）
    this._editorPromise = null;
    this._previewTimer = null;
    this._previewOn = true;

    this._build();
    this._applyMode();
    this._bindSubmit();
  }

  RichEditorInstance.prototype._build = function () {
    var i18n = _cfg.i18n;
    var self = this;

    // 容器插入到原 textarea 之前，再把 textarea 移入富文本面板
    var container = document.createElement('div');
    container.className = 'rich-editor';
    this.textarea.parentNode.insertBefore(container, this.textarea);

    // 工具条：模式切换 + Markdown 工具
    var toolbar = document.createElement('div');
    toolbar.className = 're-toolbar';
    toolbar.innerHTML =
      '<div class="btn-group btn-group-sm re-mode-group" role="group">' +
      '<button type="button" class="btn btn-outline-primary re-btn-ck">' +
      '<i class="fas fa-edit"></i> ' + i18n.richText + '</button>' +
      '<button type="button" class="btn btn-outline-primary re-btn-md">' +
      '<i class="fab fa-markdown"></i> Markdown</button>' +
      '</div>' +
      '<div class="re-md-tools btn-group btn-group-sm" role="group">' +
      '<button type="button" class="btn btn-outline-secondary re-btn-preview">' +
      '<i class="fas fa-eye"></i> ' + i18n.preview + '</button>' +
      '<button type="button" class="btn btn-outline-secondary re-btn-image">' +
      '<i class="fas fa-image"></i> ' + i18n.insertImage + '</button>' +
      '<button type="button" class="btn btn-outline-secondary re-btn-fullscreen">' +
      '<i class="fas fa-expand"></i> ' + i18n.fullscreen + '</button>' +
      '</div>';
    container.appendChild(toolbar);

    // 富文本面板：原 textarea 移入（CKEditor 初始化后由其接管显示）
    var ckBody = document.createElement('div');
    ckBody.className = 're-ck-body';
    ckBody.appendChild(this.textarea);
    container.appendChild(ckBody);

    // Markdown 面板：编辑区 + 预览区
    var mdBody = document.createElement('div');
    mdBody.className = 're-md-body';
    mdBody.style.minHeight = this.minHeight + 'px';
    var mdInput;
    if (this.mdTextarea) {
      mdInput = this.mdTextarea;
      mdInput.parentNode.removeChild(mdInput);
      mdInput.style.display = '';  // 模板中以 display:none 隐藏，移入面板后恢复显示
    } else {
      mdInput = document.createElement('textarea');
    }
    mdInput.className = 'form-control re-md-input';
    mdInput.style.minHeight = this.minHeight + 'px';
    mdInput.setAttribute('spellcheck', 'false');
    var preview = document.createElement('div');
    preview.className = 're-preview';
    preview.style.minHeight = this.minHeight + 'px';
    mdBody.appendChild(mdInput);
    mdBody.appendChild(preview);
    container.appendChild(mdBody);

    // 隐藏的文件选择框（插入图片）
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.style.display = 'none';
    container.appendChild(fileInput);

    this.container = container;
    this.ckBody = ckBody;
    this.mdBody = mdBody;
    this.mdInput = mdInput;
    this.preview = preview;
    this.fileInput = fileInput;
    this.btnCk = toolbar.querySelector('.re-btn-ck');
    this.btnMd = toolbar.querySelector('.re-btn-md');
    this.mdTools = toolbar.querySelector('.re-md-tools');

    // 事件绑定
    this.btnCk.addEventListener('click', function () { self.switchMode('ckeditor'); });
    this.btnMd.addEventListener('click', function () { self.switchMode('markdown'); });
    toolbar.querySelector('.re-btn-preview').addEventListener('click', function () {
      self._previewOn = !self._previewOn;
      mdBody.classList.toggle('re-no-preview', !self._previewOn);
      if (self._previewOn) self.updatePreview();
    });
    toolbar.querySelector('.re-btn-image').addEventListener('click', function () {
      fileInput.click();
    });
    toolbar.querySelector('.re-btn-fullscreen').addEventListener('click', function () {
      var on = container.classList.toggle('re-fullscreen');
      document.body.style.overflow = on ? 'hidden' : '';
      this.innerHTML = on
        ? '<i class="fas fa-compress"></i> ' + _cfg.i18n.exitFullscreen
        : '<i class="fas fa-expand"></i> ' + _cfg.i18n.fullscreen;
    });
    fileInput.addEventListener('change', function () { self._uploadImage(); });
    mdInput.addEventListener('input', function () {
      if (!self._previewOn) return;
      clearTimeout(self._previewTimer);
      self._previewTimer = setTimeout(function () { self.updatePreview(); }, 300);
    });
  };

  /** 按当前模式显示对应面板（初始化时调用，不做内容转换）。 */
  RichEditorInstance.prototype._applyMode = function () {
    var isMd = this.mode === 'markdown';
    this.ckBody.style.display = isMd ? 'none' : '';
    this.mdBody.style.display = isMd ? 'flex' : 'none';
    this.mdTools.style.display = isMd ? '' : 'none';
    this.btnCk.classList.toggle('active', !isMd);
    this.btnMd.classList.toggle('active', isMd);
    this._setFormatInput();
    if (isMd) {
      this.updatePreview();
    } else {
      this._ensureEditor();
    }
  };

  RichEditorInstance.prototype._setFormatInput = function () {
    if (this.formatInput) {
      this.formatInput.value = this.mode === 'markdown' ? 'markdown' : 'html';
    }
  };

  /** 创建（或返回已有的）CKEditor 实例，脚本按需加载。 */
  RichEditorInstance.prototype._ensureEditor = function () {
    var self = this;
    if (this.editor) return Promise.resolve(this.editor);
    if (this._editorPromise) return this._editorPromise;
    this._editorPromise = loadCk().then(function () {
      return window.CKEDITOR.ClassicEditor.create(self.textarea, self.ckConfig);
    }).then(function (editor) {
      self.editor = editor;
      return editor;
    }).catch(function (err) {
      window.console.error(err);
      self._editorPromise = null;
      throw err;
    });
    return this._editorPromise;
  };

  /** 模式切换（含内容双向转换；切向 Markdown 且有内容时二次确认）。 */
  RichEditorInstance.prototype.switchMode = function (target) {
    var self = this;
    if (target === this.mode) return;
    if (target === 'markdown') {
      var html = this.editor ? this.editor.getData() : this.textarea.value;
      if (html && html.trim() && !window.confirm(_cfg.i18n.confirmToMarkdown)) return;
      if (html && html.trim()) this.mdInput.value = htmlToMd(html);
      // HTML 为空时保留 mdInput 现有内容（可能是上次留存的 Markdown 原文）
      this.mode = 'markdown';
      this._applyMode();
    } else {
      var newHtml = mdToHtml(this.mdInput.value);
      this.mode = 'ckeditor';
      this._applyMode();
      this._ensureEditor().then(function (editor) {
        editor.setData(newHtml);
      });
    }
  };

  /** 刷新 Markdown 预览。 */
  RichEditorInstance.prototype.updatePreview = function () {
    this.preview.innerHTML = mdToHtml(this.mdInput.value);
  };

  /** 当前内容的 HTML（Word 导入等场景使用，跨模式）。 */
  RichEditorInstance.prototype.getHTML = function () {
    if (this.mode === 'markdown') return mdToHtml(this.mdInput.value);
    if (this.editor) return this.editor.getData();
    return this.textarea.value;
  };

  /** 设置内容（HTML），跨模式；返回 Promise。 */
  RichEditorInstance.prototype.setHTML = function (html) {
    var self = this;
    if (this.mode === 'markdown') {
      this.mdInput.value = htmlToMd(html);
      this.updatePreview();
      return Promise.resolve();
    }
    return this._ensureEditor().then(function (editor) {
      editor.setData(html);
      self.textarea.value = html;
    });
  };

  /** 提交前回写：富文本→textarea 写 HTML；Markdown→textarea 写渲染后 HTML + 格式域。 */
  RichEditorInstance.prototype.syncToTextarea = function () {
    if (this.mode === 'markdown') {
      this.textarea.value = mdToHtml(this.mdInput.value);
    } else if (this.editor) {
      this.textarea.value = this.editor.getData();
    }
    this._setFormatInput();
  };

  RichEditorInstance.prototype._bindSubmit = function () {
    var self = this;
    if (this.textarea.form) {
      this.textarea.form.addEventListener('submit', function () {
        self.syncToTextarea();
      });
    }
  };

  /** Markdown 模式插入图片：复用通用上传端点，成功后光标处插入 ![](url)。 */
  RichEditorInstance.prototype._uploadImage = function () {
    var self = this;
    var file = this.fileInput.files[0];
    this.fileInput.value = '';
    if (!file || !this.uploadUrl) return;

    var fd = new FormData();
    fd.append('upload', file);
    fd.append('type', this.uploadType);

    var btn = this.mdTools.querySelector('.re-btn-image');
    var original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> ' + _cfg.i18n.uploading;

    var headers = { 'X-Requested-With': 'XMLHttpRequest' };
    if (window.csrfToken) headers['X-CSRF-Token'] = window.csrfToken;

    window.fetch(this.uploadUrl, { method: 'POST', body: fd, headers: headers })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (res) {
        if (!res.ok || res.data.error) throw new Error(res.data.error || _cfg.i18n.uploadFailed);
        var ta = self.mdInput;
        var insert = '![' + (res.data.filename || '') + '](' + res.data.url + ')';
        var start = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
        var end = ta.selectionEnd != null ? ta.selectionEnd : start;
        ta.value = ta.value.slice(0, start) + insert + ta.value.slice(end);
        ta.focus();
        ta.selectionStart = ta.selectionEnd = start + insert.length;
        self.updatePreview();
      })
      .catch(function (err) { window.alert(_cfg.i18n.uploadFailed + '：' + err.message); })
      .finally(function () {
        btn.disabled = false;
        btn.innerHTML = original;
      });
  };

  window.RichEditor = {
    configure: configure,
    init: init,
    loadCk: loadCk,
    instances: instances
  };
})();
