/**
 * v3.0.0 页面构建器 —— 画布预览桥
 * 运行于后台编辑器的 iframe 内：
 * 1. 点击选中组件 -> postMessage(select)
 * 2. 原生拖拽（移动已有节点 / 从左侧组件库新增）-> postMessage(drop)
 * 3. 接收父窗口 select 消息同步高亮
 */
(function () {
  'use strict';

  var selectedId = null;
  var dragOverContainer = null;
  var insertIndex = 0;
  var indicator = null;

  function nodes() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-zbw-id]'));
  }

  function nodeById(id) {
    return document.querySelector('[data-zbw-id="' + cssEscape(id) + '"]');
  }

  function cssEscape(v) {
    return String(v).replace(/(["\\])/g, '\\$1');
  }

  function post(msg) {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(Object.assign({ source: 'zbw-preview' }, msg), '*');
    }
  }

  /* 注入类型小标签 */
  function injectTags() {
    nodes().forEach(function (el) {
      if (el.querySelector(':scope > .zbw-tag')) return;
      var tag = document.createElement('span');
      tag.className = 'zbw-tag';
      tag.textContent = el.getAttribute('data-zbw-type');
      el.insertBefore(tag, el.firstChild);
    });
  }

  function markSelected(id) {
    selectedId = id;
    nodes().forEach(function (el) {
      el.classList.toggle('zbw-selected', el.getAttribute('data-zbw-id') === id);
    });
  }

  /* ---------- 选择 ---------- */
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('[data-zbw-id]') : null;
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    markSelected(el.getAttribute('data-zbw-id'));
    post({ type: 'select', id: el.getAttribute('data-zbw-id') });
  }, true);

  /* ---------- 拖拽 ---------- */
  document.addEventListener('dragstart', function (e) {
    var el = e.target.closest ? e.target.closest('[data-zbw-id]') : null;
    if (!el) return;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', JSON.stringify({
      kind: 'move', nodeId: el.getAttribute('data-zbw-id')
    }));
    el.classList.add('zbw-dragging-source');
  }, true);

  document.addEventListener('dragend', function () {
    clearDragOver();
    nodes().forEach(function (el) { el.classList.remove('zbw-dragging-source'); });
  }, true);

  function childNodes(container) {
    return Array.prototype.slice.call(
      container.querySelectorAll(':scope > [data-zbw-id]'));
  }

  /* 判断容器主轴：横向排列 -> 'x'，否则 'y' */
  function flowAxis(container, kids) {
    if (kids.length >= 2) {
      var a = kids[0].getBoundingClientRect();
      var b = kids[1].getBoundingClientRect();
      if (Math.abs(a.top - b.top) < 4 && Math.abs(a.left - b.left) > 4) return 'x';
    }
    var st = window.getComputedStyle(container);
    if (st && (st.display === 'flex' || st.display === 'inline-flex')
        && st.flexDirection.indexOf('row') === 0) return 'x';
    return 'y';
  }

  function computeInsertIndex(container, clientX, clientY) {
    var kids = childNodes(container);
    if (!kids.length) return 0;
    var axis = flowAxis(container, kids);
    var idx = kids.length;
    for (var i = 0; i < kids.length; i++) {
      var r = kids[i].getBoundingClientRect();
      if (axis === 'x') {
        if (clientX < r.left + r.width / 2) { idx = i; break; }
      } else {
        if (clientY < r.top + r.height / 2) { idx = i; break; }
      }
    }
    return { idx: idx, axis: axis, kids: kids };
  }

  function showIndicator(container, info) {
    if (!indicator) {
      indicator = document.createElement('div');
      indicator.className = 'zbw-drop-indicator';
    }
    container.style.position = container.style.position || 'relative';
    if (indicator.parentNode !== container) container.appendChild(indicator);
    var idx = info.idx;
    indicator.style.top = '';
    indicator.style.left = '';
    indicator.style.right = '';
    indicator.style.width = '';
    indicator.style.height = '3px';
    if (info.kids.length === 0) {
      indicator.style.top = '4px'; indicator.style.left = '4px';
      indicator.style.right = '4px';
    } else if (info.axis === 'x') {
      var r = idx < info.kids.length
        ? info.kids[idx].getBoundingClientRect()
        : info.kids[info.kids.length - 1].getBoundingClientRect();
      var cr = container.getBoundingClientRect();
      indicator.style.width = '3px';
      indicator.style.height = Math.round(Math.max(r.height, 24)) + 'px';
      indicator.style.top = Math.round(r.top - cr.top) + 'px';
      indicator.style.left = Math.round(
        (idx < info.kids.length ? r.left : r.right) - cr.left) + 'px';
    } else {
      var rt = idx < info.kids.length
        ? info.kids[idx].getBoundingClientRect()
        : info.kids[info.kids.length - 1].getBoundingClientRect();
      var crt = container.getBoundingClientRect();
      indicator.style.left = '4px';
      indicator.style.right = '4px';
      indicator.style.top = Math.round(
        (idx < info.kids.length ? rt.top : rt.bottom) - crt.top) + 'px';
    }
  }

  function clearDragOver() {
    if (dragOverContainer) {
      dragOverContainer.classList.remove('zbw-dragover');
      dragOverContainer = null;
    }
    if (indicator) { indicator.remove(); indicator = null; }
  }

  document.addEventListener('dragover', function (e) {
    var container = e.target.closest ? e.target.closest('[data-zbw-children]') : null;
    if (!container) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragOverContainer !== container) {
      if (dragOverContainer) dragOverContainer.classList.remove('zbw-dragover');
      dragOverContainer = container;
      container.classList.add('zbw-dragover');
    }
    var info = computeInsertIndex(container, e.clientX, e.clientY);
    insertIndex = info.idx;
    showIndicator(container, info);
  }, true);

  document.addEventListener('dragleave', function (e) {
    if (!dragOverContainer) return;
    if (e.clientX <= 0 || e.clientY <= 0
        || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight) {
      clearDragOver();
    }
  }, true);

  document.addEventListener('drop', function (e) {
    var container = e.target.closest ? e.target.closest('[data-zbw-children]') : null;
    if (!container) return;
    e.preventDefault();
    e.stopPropagation();
    var info = computeInsertIndex(container, e.clientX, e.clientY);
    var raw = e.dataTransfer.getData('text/plain');
    var payload = null;
    try { payload = raw ? JSON.parse(raw) : {}; } catch (err) { payload = {}; }
    post({
      type: 'drop',
      parentId: container.getAttribute('data-zbw-children'),
      index: info.idx,
      payload: payload,
    });
    clearDragOver();
  }, true);

  /* ---------- 父子窗口通信 ---------- */
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.target !== 'zbw-preview') return;
    if (d.type === 'select') markSelected(d.id || null);
    if (d.type === 'ping') post({ type: 'pong', selectedId: selectedId });
  });

  /* 父窗口可能加载了缓存的旧画布，通知其就绪以便重新挂接 */
  function notifyReady() {
    injectTags();
    post({ type: 'ready' });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', notifyReady);
  } else {
    notifyReady();
  }
})();
