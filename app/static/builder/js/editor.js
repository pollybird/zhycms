/**
 * v3.0.0 页面构建器编辑器（原生 ES Module，无构建链）
 *
 * 职责：
 *  - 维护布局 JSON 状态树（增删移动/属性编辑）
 *  - 与 iframe 画布（preview_bridge.js）postMessage 通信
 *  - 组件库 / 属性表单 / 图层树三个面板
 *  - 防抖自动保存草稿、发布、修订回滚
 */
'use strict';

const root = document.getElementById('zbw-app');
const PAGE_ID = root.dataset.pageId;
const PREVIEW_URL = root.dataset.previewUrl;
const CAN_PUBLISH = root.dataset.canPublish === '1';

const API = {
  page: `/admin/builder/api/pages/${PAGE_ID}`,
  widgets: '/admin/builder/api/widgets',
  columns: '/admin/builder/api/columns?type=list',
  draft: `/admin/builder/api/pages/${PAGE_ID}/draft`,
  publish: `/admin/builder/api/pages/${PAGE_ID}/publish`,
  revisions: `/admin/builder/api/pages/${PAGE_ID}/revisions`,
  rollback: `/admin/builder/api/pages/${PAGE_ID}/rollback`,
  upload: '/admin/upload',
};

const CAT_LABELS = { layout: '布局组件', basic: '基础组件', data: '数据组件' };
const CAT_ORDER = ['layout', 'basic', 'data'];
const LOCALES = [['zh', '中文'], ['en', 'English']];

const state = {
  scope: 'home',
  layout: { version: 1, root: [] },
  catalog: {},
  widgets: new Map(),
  listColumns: [],
  selectedId: null,
  dirty: false,
  saving: false,
  saveTimer: null,
  renderTimer: null,
  activeLocale: 'zh',
};

const iframe = document.getElementById('zbw-canvas');
const saveStatus = document.getElementById('zbw-save-status');

/* ============================================================
 * 工具
 * ============================================================ */

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function genId() {
  return 'n_' + Math.random().toString(16).slice(2, 10);
}

function deepClone(v) {
  return JSON.parse(JSON.stringify(v));
}

function findNode(id, nodes) {
  nodes = nodes || state.layout.root;
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findNode(id, n.children || []);
    if (hit) return hit;
  }
  return null;
}

function findParentNode(id, nodes, parent) {
  nodes = nodes || state.layout.root;
  for (const n of nodes) {
    if (n.id === id) return { parent: parent || null, list: nodes, index: nodes.indexOf(n) };
    const hit = findParentNode(id, n.children || [], n);
    if (hit) return hit;
  }
  return null;
}

function isDescendant(maybeAncestorId, nodeId) {
  const a = findNode(maybeAncestorId);
  if (!a) return false;
  return !!findNode(nodeId, a.children || []);
}

function canContain(parentType, childType) {
  if (!parentType) return true; // 根节点放行，由服务端兜底
  const w = state.widgets.get(parentType);
  if (!w) return false;
  const allowed = w.allowed_children || [];
  if (!allowed.length) return false;
  return allowed.indexOf('*') >= 0 || allowed.indexOf(childType) >= 0;
}

function nearestContainer(nodeId, childType) {
  if (!nodeId) return null;
  let cur = findNode(nodeId);
  while (cur) {
    if (canContain(cur.type, childType)) return cur.id;
    const loc = findParentNode(cur.id);
    cur = loc && loc.parent;
  }
  return null;
}

function markDirty() {
  state.dirty = true;
  saveStatus.textContent = '有未保存修改…';
  saveStatus.className = 'zbw-save-status dirty';
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveDraft, 800);
}

function scheduleRender() {
  clearTimeout(state.renderTimer);
  state.renderTimer = setTimeout(reloadCanvas, 350);
}

function reloadCanvas() {
  const url = PREVIEW_URL + (PREVIEW_URL.indexOf('?') >= 0 ? '&' : '?') + 't=' + Date.now();
  iframe.src = url;
}

function selectNode(id) {
  state.selectedId = id;
  if (iframe.contentWindow) {
    iframe.contentWindow.postMessage(
      { target: 'zbw-preview', type: 'select', id: id || null }, '*');
  }
  renderProps();
  renderOutline();
}

/* ============================================================
 * 树操作
 * ============================================================ */

function createNode(type) {
  const w = state.widgets.get(type);
  if (!w) return null;
  const node = {
    id: genId(),
    type,
    props: deepClone(w.default_props || {}),
    visibility: {},
    children: [],
  };
  for (let i = 0; i < (w.default_children || 0); i++) {
    const childType = (w.allowed_children || []).find(t => t !== '*');
    if (childType) node.children.push(createNode(childType));
  }
  return node;
}

function addWidget(type, parentId, index) {
  const node = createNode(type);
  if (!node) return;
  const list = parentId ? (findNode(parentId).children || []) : state.layout.root;
  if (typeof index !== 'number') index = list.length;
  list.splice(index, 0, node);
  selectNode(node.id);
  markDirty();
  scheduleRender();
}

function addFromCatalog(type) {
  const w = state.widgets.get(type);
  if (!w || w.enabled === false) return;
  // 优先放入当前选中的可容纳容器，否则向上找，最后放根
  let target = nearestContainer(state.selectedId, type);
  if (!target) {
    target = null; // root
  }
  addWidget(type, target);
}

function moveNode(nodeId, newParentId, index) {
  const loc = findParentNode(nodeId);
  if (!loc) return;
  const node = findNode(nodeId);
  const newParent = newParentId === '__root__' ? null : newParentId;
  if (newParent && !canContain(findNode(newParent).type, node.type)) {
    reloadCanvas();
    return;
  }
  if (newParent && isDescendant(nodeId, newParent)) {
    reloadCanvas();
    return; // 禁止移入自己的子孙
  }
  const sameList = loc.list === (newParent ? findNode(newParent).children : state.layout.root);
  loc.list.splice(loc.index, 1);
  const destList = newParent ? findNode(newParent).children : state.layout.root;
  let to = index;
  if (sameList && loc.index < index) to = index - 1;
  to = Math.max(0, Math.min(to, destList.length));
  destList.splice(to, 0, node);
  selectNode(nodeId);
  markDirty();
  scheduleRender();
}

function deleteNode(id) {
  const loc = findParentNode(id);
  if (!loc) return;
  loc.list.splice(loc.index, 1);
  state.selectedId = null;
  markDirty();
  scheduleRender();
  renderProps();
  renderOutline();
}

function duplicateNode(id) {
  const loc = findParentNode(id);
  if (!loc) return;
  const clone = deepClone(loc.list[loc.index]);
  const reId = n => { n.id = genId(); (n.children || []).forEach(reId); };
  reId(clone);
  loc.list.splice(loc.index + 1, 0, clone);
  selectNode(clone.id);
  markDirty();
  scheduleRender();
}

function shiftNode(id, delta) {
  const loc = findParentNode(id);
  if (!loc) return;
  const to = loc.index + delta;
  if (to < 0 || to >= loc.list.length) return;
  const [n] = loc.list.splice(loc.index, 1);
  loc.list.splice(to, 0, n);
  markDirty();
  scheduleRender();
  renderOutline();
}

/* ============================================================
 * 保存 / 发布 / 修订
 * ============================================================ */

async function api(url, opts) {
  const res = await fetch(url, Object.assign({
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
  }, opts));
  let data = {};
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `请求失败 (${res.status})`);
  }
  return data;
}

async function saveDraft() {
  if (!state.dirty || state.saving) {
    if (state.saving) state.saveTimer = setTimeout(saveDraft, 500);
    return;
  }
  state.saving = true;
  saveStatus.textContent = '保存中…';
  saveStatus.className = 'zbw-save-status saving';
  try {
    const r = await api(API.draft, {
      method: 'POST',
      body: JSON.stringify({ layout: state.layout }),
    });
    state.dirty = false;
    saveStatus.textContent = `草稿已保存 ${r.saved_at || ''}`;
    saveStatus.className = 'zbw-save-status saved';
    scheduleRender();
  } catch (e) {
    saveStatus.textContent = '保存失败：' + e.message;
    saveStatus.className = 'zbw-save-status error';
    state.saveTimer = setTimeout(saveDraft, 2000);
  } finally {
    state.saving = false;
  }
}

async function publishLayout() {
  // 先确保草稿落盘
  if (state.dirty) {
    await saveDraft();
    await new Promise(r => setTimeout(r, 400));
  }
  const note = document.getElementById('zbw-publish-note').value;
  const r = await api(API.publish, {
    method: 'POST',
    body: JSON.stringify({ layout: state.layout, note }),
  });
  return r;
}

/* ============================================================
 * 组件库面板
 * ============================================================ */

function renderCatalog() {
  const box = document.getElementById('zbw-widget-catalog');
  let html = '';
  for (const cat of CAT_ORDER) {
    const list = state.catalog[cat] || [];
    if (!list.length) continue;
    html += `<div class="zbw-widget-group-title">${CAT_LABELS[cat]}</div>`;
    for (const w of list) {
      const disabled = w.enabled === false;
      html += `
        <div class="zbw-widget-item${disabled ? ' disabled' : ''}" data-type="${esc(w.type)}"
             title="${esc(w.description || w.label)}">
          <span class="zbw-widget-icon"><i class="fas ${esc(w.icon)}"></i></span>
          <span>${esc(w.label)}</span>
          ${disabled ? '<span class="zbw-widget-badge ml-auto">插件未启用</span>' : ''}
          ${w.owner !== 'core' && !disabled ? '<span class="zbw-widget-badge ml-auto text-muted small">插件</span>' : ''}
        </div>`;
    }
  }
  box.innerHTML = html;
  box.querySelectorAll('.zbw-widget-item').forEach(el => {
    el.addEventListener('click', () => addFromCatalog(el.dataset.type));
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({
        kind: 'new', widgetType: el.dataset.type,
      }));
      e.dataTransfer.effectAllowed = 'copy';
    });
    el.setAttribute('draggable', 'true');
  });
}

/* ============================================================
 * 属性面板
 * ============================================================ */

function getLocalized(node, key) {
  const v = node.props[key];
  if (v && typeof v === 'object') return v[state.activeLocale] || '';
  return v == null ? '' : v;
}

function setLocalized(node, key, val) {
  const v = node.props[key];
  if (v && typeof v === 'object') {
    v[state.activeLocale] = val;
  } else {
    node.props[key] = state.activeLocale === 'zh' ? val
      : Object.assign({ zh: v || '' }, { [state.activeLocale]: val });
  }
}

function fieldValue(node, field) {
  let v = node.props[field.key];
  if (field.localized) return getLocalized(node, field.key);
  if (v == null) v = field.default != null ? field.default : '';
  return v;
}

function setField(node, field, val) {
  if (field.localized) setLocalized(node, field.key, val);
  else node.props[field.key] = val;
  markDirty();
  scheduleRender();
}

function renderProps() {
  const box = document.getElementById('zbw-props-form');
  const node = state.selectedId ? findNode(state.selectedId) : null;
  if (!node) {
    box.innerHTML = '<p class="text-muted text-center py-4">点击画布中的组件进行编辑</p>';
    return;
  }
  const w = state.widgets.get(node.type);
  let html = `<div class="mb-2 pb-2 border-bottom">
      <strong><i class="fas ${esc(w ? w.icon : 'puzzle-piece')}"></i> ${esc(w ? w.label : node.type)}</strong>
      <div class="btn-group btn-group-sm float-right">
        <button class="btn btn-default" data-act="up" title="上移">↑</button>
        <button class="btn btn-default" data-act="down" title="下移">↓</button>
        <button class="btn btn-default" data-act="copy" title="复制"><i class="far fa-copy"></i></button>
        <button class="btn btn-danger" data-act="del" title="删除"><i class="fas fa-trash"></i></button>
      </div>
    </div>`;

  const hasLocalized = (w.prop_schema || []).some(f => f.localized);
  if (hasLocalized) {
    html += '<div class="btn-group btn-group-xs zbw-locale-tabs mb-2">';
    for (const [code, label] of LOCALES) {
      html += `<button class="btn btn-default btn-sm zbw-locale-btn ${state.activeLocale === code ? 'active' : ''}" data-locale="${code}">${label}</button>`;
    }
    html += '</div>';
  }

  for (const field of w.prop_schema || []) {
    html += renderField(node, field);
  }

  // 可见性
  const vis = node.visibility || {};
  html += `<hr><div class="zbw-field">
    <label>可见性</label>
    <div class="form-check">
      <input class="form-check-input" type="checkbox" id="zbw-vis-member">
      <label class="form-check-label" for="zbw-vis-member">仅登录会员可见</label>
    </div>
    <div class="mt-1">
      <label class="d-inline mr-2"><input type="checkbox" class="zbw-vis-loc" value="zh" ${(!vis.locales || vis.locales.indexOf('zh') >= 0) ? 'checked' : ''}> 中文</label>
      <label class="d-inline"><input type="checkbox" class="zbw-vis-loc" value="en" ${(!vis.locales || vis.locales.indexOf('en') >= 0) ? 'checked' : ''}> English</label>
    </div>
    <div class="zbw-field-help">取消勾选某语言则该语言页面中隐藏组件</div>
  </div>`;

  box.innerHTML = html;
  bindProps(box, node, w);
}

function renderField(node, field) {
  const key = esc(field.key);
  const label = esc(field.label || field.key);
  const val = fieldValue(node, field);
  const help = field.help ? `<div class="zbw-field-help">${esc(field.help)}</div>` : '';
  const inputAttrs = `data-key="${key}" data-type="${field.type}"`;
  let inner = '';
  switch (field.type) {
    case 'textarea':
      inner = `<textarea class="form-control form-control-sm" rows="3" ${inputAttrs}>${esc(val)}</textarea>`;
      break;
    case 'richtext':
      inner = `<div class="input-group input-group-sm">
          <input class="form-control" readonly value="${esc(String(val).replace(/<[^>]+>/g, '').slice(0, 40))}" placeholder="富文本内容">
          <div class="input-group-append">
            <button class="btn btn-default" data-richtext="${key}"><i class="fas fa-edit"></i> 编辑</button>
          </div>
        </div>`;
      break;
    case 'number':
      inner = `<input type="number" class="form-control form-control-sm" value="${esc(val)}" ${inputAttrs}>`;
      break;
    case 'select':
      inner = `<select class="form-control form-control-sm" ${inputAttrs}>`;
      for (const opt of field.options || []) {
        const ov = Array.isArray(opt) ? opt[0] : opt;
        const ol = Array.isArray(opt) ? opt[1] : opt;
        inner += `<option value="${esc(ov)}" ${String(ov) === String(val) ? 'selected' : ''}>${esc(ol)}</option>`;
      }
      inner += '</select>';
      break;
    case 'toggle':
      inner = `<div class="form-check">
        <input type="checkbox" class="form-check-input" ${val ? 'checked' : ''} ${inputAttrs}></div>`;
      break;
    case 'color':
      inner = `<div class="input-group input-group-sm">
          <input type="color" class="form-control" style="max-width:42px;padding:2px" value="${esc(val || '#333333')}" ${inputAttrs}>
          <input type="text" class="form-control" value="${esc(val)}" data-color-text="${key}">
        </div>`;
      break;
    case 'image':
      inner = `<input type="text" class="form-control form-control-sm mb-1" value="${esc(val)}" placeholder="/static/... 或 https://" ${inputAttrs}>
        <div><input type="file" accept="image/*" data-upload="${key}" class="d-none">
        <button class="btn btn-default btn-sm" data-upload-btn="${key}"><i class="fas fa-upload"></i> 上传图片</button></div>
        ${val ? `<img src="${esc(val)}" class="zbw-image-preview" data-imgprev="${key}">` : ''}`;
      break;
    case 'icon':
      inner = `<div class="input-group input-group-sm zbw-icon-picker-wrap">
          <div class="input-group-prepend"><span class="input-group-text"><i class="${esc(val || 'fas fa-star')}"></i></span></div>
          <input type="text" class="form-control" value="${esc(val)}" placeholder="fas fa-star" ${inputAttrs}>
        </div>`;
      break;
    case 'column':
      inner = `<select class="form-control form-control-sm" ${inputAttrs}>
        <option value="">${field.bind === 'auto' ? '自动（当前栏目）' : '请选择栏目'}</option>
        ${state.listColumns.map(c => `<option value="${c.id}" ${String(c.id) === String(val) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
      </select>`;
      break;
    case 'repeater':
      inner = renderRepeater(node, field, val);
      break;
    case 'url':
    case 'text':
    default:
      inner = `<input type="text" class="form-control form-control-sm" value="${esc(val)}" ${inputAttrs}>`;
  }
  return `<div class="zbw-field"><label>${label}</label>${inner}${help}</div>`;
}

function renderRepeater(node, field, items) {
  items = Array.isArray(items) ? items : [];
  let html = `<div data-repeater="${esc(field.key)}">`;
  items.forEach((item, i) => {
    html += `<div class="zbw-repeater-item" data-index="${i}">
      <div class="zbw-repeater-item-head">
        <strong class="small">#${i + 1}</strong>
        <button class="btn btn-danger btn-xs" data-rep-del="${esc(field.key)}" data-index="${i}">
          <i class="fas fa-times"></i></button>
      </div>`;
    for (const sf of field.fields || []) {
      const sv = item[sf.key] == null ? (sf.default || '') : item[sf.key];
      html += `<label class="small text-muted">${esc(sf.label || sf.key)}</label>`;
      if (sf.type === 'textarea') {
        html += `<textarea class="form-control form-control-sm mb-1" rows="2"
          data-rep-key="${esc(field.key)}" data-rep-index="${i}" data-subkey="${esc(sf.key)}">${esc(sv)}</textarea>`;
      } else if (sf.type === 'toggle') {
        html += `<input type="checkbox" class="mb-1" ${sv ? 'checked' : ''}
          data-rep-key="${esc(field.key)}" data-rep-index="${i}" data-subkey="${esc(sf.key)}">`;
      } else if (sf.type === 'image') {
        html += `<input type="text" class="form-control form-control-sm mb-1" value="${esc(sv)}"
          data-rep-key="${esc(field.key)}" data-rep-index="${i}" data-subkey="${esc(sf.key)}">`;
      } else if (sf.type === 'number') {
        html += `<input type="number" class="form-control form-control-sm mb-1" value="${esc(sv)}"
          data-rep-key="${esc(field.key)}" data-rep-index="${i}" data-subkey="${esc(sf.key)}">`;
      } else {
        html += `<input type="text" class="form-control form-control-sm mb-1" value="${esc(sv)}"
          data-rep-key="${esc(field.key)}" data-rep-index="${i}" data-subkey="${esc(sf.key)}">`;
      }
    }
    html += '</div>';
  });
  html += `<button class="btn btn-outline-primary btn-sm btn-block" data-rep-add="${esc(field.key)}">
    <i class="fas fa-plus"></i> 添加一项</button></div>`;
  return html;
}

function bindProps(box, node, widget) {
  box.querySelectorAll('.zbw-locale-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeLocale = btn.dataset.locale;
      renderProps();
    });
  });

  box.querySelector('[data-act="del"]').addEventListener('click', () => {
    if (confirm('确定删除该组件？')) deleteNode(node.id);
  });
  box.querySelector('[data-act="copy"]').addEventListener('click', () => duplicateNode(node.id));
  box.querySelector('[data-act="up"]').addEventListener('click', () => shiftNode(node.id, -1));
  box.querySelector('[data-act="down"]').addEventListener('click', () => shiftNode(node.id, 1));

  box.querySelectorAll('[data-key]').forEach(el => {
    const evt = el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input';
    el.addEventListener(evt, () => {
      const key = el.dataset.key;
      const field = (widget.prop_schema || []).find(f => f.key === key);
      let v;
      if (el.type === 'checkbox') v = el.checked;
      else if (field && field.type === 'number') v = el.value === '' ? '' : Number(el.value);
      else v = el.value;
      if (field && field.type === 'number' && v === '') {
        delete node.props[key];
      } else setField(node, field, v);
    });
  });

  // color 文本框同步
  box.querySelectorAll('[data-color-text]').forEach(el => {
    el.addEventListener('input', () => {
      const key = el.dataset.colorText;
      node.props[key] = el.value;
      const picker = box.querySelector(`[data-key="${key}"][type="color"]`);
      if (picker && /^#[0-9a-fA-F]{6}$/.test(el.value)) picker.value = el.value;
      markDirty(); scheduleRender();
    });
  });

  // 图片上传
  box.querySelectorAll('[data-upload-btn]').forEach(btn => {
    btn.addEventListener('click', () => {
      box.querySelector(`[data-upload="${btn.dataset.uploadBtn}"]`).click();
    });
  });
  box.querySelectorAll('[data-upload]').forEach(fileEl => {
    fileEl.addEventListener('change', async () => {
      const key = fileEl.dataset.upload;
      const f = fileEl.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append('file', f);
      fd.append('type', 'builder');
      btnBusy(fileEl, true);
      try {
        const res = await fetch(API.upload, { method: 'POST', body: fd, credentials: 'same-origin' });
        const data = await res.json();
        if (!res.ok || !data.url) throw new Error(data.error || '上传失败');
        node.props[key] = data.url;
        markDirty();
        renderProps();
        scheduleRender();
      } catch (e) {
        alert('上传失败：' + e.message);
      } finally {
        btnBusy(fileEl, false);
      }
    });
  });

  // repeater
  box.querySelectorAll('[data-rep-add]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.repAdd;
      const field = (widget.prop_schema || []).find(f => f.key === key);
      const items = Array.isArray(node.props[key]) ? node.props[key] : [];
      const item = {};
      for (const sf of field.fields || []) if (sf.default != null) item[sf.key] = sf.default;
      items.push(item);
      node.props[key] = items;
      markDirty(); renderProps();
    });
  });
  box.querySelectorAll('[data-rep-del]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.repDel;
      const items = node.props[key] || [];
      items.splice(Number(btn.dataset.index), 1);
      markDirty(); renderProps(); scheduleRender();
    });
  });
  box.querySelectorAll('[data-rep-key]').forEach(el => {
    el.addEventListener('input', () => {
      const items = node.props[el.dataset.repKey] || [];
      const item = items[Number(el.dataset.repIndex)];
      if (!item) return;
      let v = el.value;
      if (el.type === 'checkbox') v = el.checked;
      item[el.dataset.subkey] = v;
      markDirty();
      scheduleRender();
    });
    el.addEventListener('change', () => {
      const items = node.props[el.dataset.repKey] || [];
      const item = items[Number(el.dataset.repIndex)];
      if (item && el.type === 'checkbox') item[el.dataset.subkey] = el.checked;
    });
  });

  // 富文本弹窗
  box.querySelectorAll('[data-richtext]').forEach(btn => {
    btn.addEventListener('click', () => openRichtext(node, btn.dataset.richtext));
  });

  // 可见性
  const memberCb = document.getElementById('zbw-vis-member');
  memberCb.checked = !!(node.visibility && node.visibility.member_only);
  memberCb.addEventListener('change', () => {
    node.visibility = node.visibility || {};
    node.visibility.member_only = memberCb.checked || undefined;
    if (!memberCb.checked) delete node.visibility.member_only;
    markDirty(); scheduleRender();
  });
  box.querySelectorAll('.zbw-vis-loc').forEach(cb => {
    cb.addEventListener('change', () => {
      node.visibility = node.visibility || {};
      const locs = Array.from(box.querySelectorAll('.zbw-vis-loc:checked')).map(x => x.value);
      if (locs.length === 2) delete node.visibility.locales;
      else node.visibility.locales = locs;
      markDirty(); scheduleRender();
    });
  });
}

function btnBusy(fileEl, on) {
  const btn = document.querySelector(`[data-upload-btn="${fileEl.dataset.upload}"]`);
  if (!btn) return;
  btn.disabled = on;
  btn.innerHTML = on ? '<i class="fas fa-spinner fa-spin"></i> 上传中' : '<i class="fas fa-upload"></i> 上传图片';
}

/* ============================================================
 * 图层树
 * ============================================================ */

function renderOutline() {
  const box = document.getElementById('zbw-outline-tree');
  if (!state.layout.root.length) {
    box.innerHTML = '<div class="zbw-ol-placeholder">画布为空，从左侧添加组件</div>';
    return;
  }
  box.innerHTML = state.layout.root.map(n => outlineNode(n, 0)).join('');
  box.querySelectorAll('.zbw-outline-node').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.closest('button')) return;
      selectNode(el.dataset.id);
    });
  });
  box.querySelectorAll('[data-ol]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const id = btn.closest('.zbw-outline-node').dataset.id;
      const act = btn.dataset.ol;
      if (act === 'del') { if (confirm('确定删除？')) deleteNode(id); }
      if (act === 'copy') duplicateNode(id);
      if (act === 'up') shiftNode(id, -1);
      if (act === 'down') shiftNode(id, 1);
    });
  });
}

function outlineNode(n, depth) {
  const w = state.widgets.get(n.type);
  const label = w ? w.label : n.type;
  const sel = n.id === state.selectedId ? ' selected' : '';
  const pad = depth * 12;
  let html = `<div class="zbw-outline-node${sel}" data-id="${esc(n.id)}" style="padding-left:${4 + pad}px">
    <span class="zbw-ol-label"><i class="fas ${esc(w ? w.icon : 'puzzle-piece')} fa-fw"></i> ${esc(label)}</span>
    <span class="zbw-ol-ops">
      <button class="btn btn-default btn-xs" data-ol="up" title="上移">↑</button>
      <button class="btn btn-default btn-xs" data-ol="down" title="下移">↓</button>
      <button class="btn btn-default btn-xs" data-ol="copy" title="复制"><i class="far fa-copy"></i></button>
      <button class="btn btn-danger btn-xs" data-ol="del" title="删除"><i class="fas fa-times"></i></button>
    </span></div>`;
  if ((n.children || []).length) {
    html += `<div class="zbw-ol-children">${n.children.map(c => outlineNode(c, depth + 1)).join('')}</div>`;
  }
  return html;
}

/* ============================================================
 * 富文本弹窗（CKEditor5 自托管 super-build）
 * ============================================================ */

let ckLoading = null;
let ckEditor = null;
let rtContext = null; // {node, key}

function loadCKEditor() {
  if (window.CKEDITOR) return Promise.resolve();
  if (ckLoading) return ckLoading;
  ckLoading = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/static/ckeditor5/ckeditor.js';
    s.onload = () => {
      const t = document.createElement('script');
      t.src = '/static/ckeditor5/translations/zh-cn.js';
      t.onload = resolve;
      t.onerror = reject;
      document.head.appendChild(t);
    };
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return ckLoading;
}

async function openRichtext(node, key) {
  const modal = $('#zbw-richtext-modal');
  const ta = document.getElementById('zbw-richtext-area');
  rtContext = { node, key };
  document.getElementById('zbw-rt-locale-label').textContent =
    state.activeLocale === 'zh' ? '中文' : 'English';
  await loadCKEditor();
  if (ckEditor) { await ckEditor.destroy(); ckEditor = null; }
  ta.value = getLocalized(node, key) || '';
  modal.modal('show');
  const config = {
    language: 'zh-cn',
    simpleUpload: { uploadUrl: API.upload + '?type=content' },
    toolbar: ['undo', 'redo', '|', 'heading', 'bold', 'italic', 'link',
      'bulletedList', 'numberedList', '|', 'alignment:left',
      'alignment:center', 'alignment:right', '|', 'blockQuote',
      'insertTable', 'mediaEmbed', '|', 'fontColor', 'fontBackgroundColor'],
  };
  setTimeout(() => {
    window.CKEDITOR.ClassicEditor.create(ta, config).then(ed => { ckEditor = ed; })
      .catch(err => console.error('CKEditor init failed', err));
  }, 300);
}

document.getElementById('zbw-rt-save').addEventListener('click', async () => {
  if (ckEditor) {
    const val = ckEditor.getData();
    setLocalized(rtContext.node, rtContext.key, val);
    await ckEditor.destroy();
    ckEditor = null;
  }
  $('#zbw-richtext-modal').modal('hide');
  markDirty();
  renderProps();
  scheduleRender();
});
$('#zbw-richtext-modal').on('hidden.bs.modal', async () => {
  if (ckEditor) { try { await ckEditor.destroy(); } catch (e) {} ckEditor = null; }
});

/* ============================================================
 * 修订历史 / 发布弹窗
 * ============================================================ */

document.getElementById('zbw-btn-revisions').addEventListener('click', async () => {
  $('#zbw-revisions-modal').modal('show');
  const body = document.getElementById('zbw-revisions-body');
  body.innerHTML = '<tr><td colspan="4" class="text-center text-muted">加载中…</td></tr>';
  try {
    const r = await api(API.revisions);
    if (!r.revisions.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-center text-muted">暂无发布记录</td></tr>';
      return;
    }
    body.innerHTML = r.revisions.map(rev => `
      <tr><td>#${rev.id}</td><td>${esc(rev.created_at)}</td>
      <td>${esc(rev.note || '—')}</td>
      <td><button class="btn btn-warning btn-xs" data-rollback="${rev.id}">回滚到此版本</button></td>
      </tr>`).join('');
    body.querySelectorAll('[data-rollback]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('回滚会将该快照载入草稿（不会立即发布，需再次点发布）。确定？')) return;
        try {
          const r2 = await api(API.rollback, {
            method: 'POST',
            body: JSON.stringify({ revision_id: Number(btn.dataset.rollback) }),
          });
          state.layout = r2.layout;
          state.dirty = false;
          state.selectedId = null;
          $('#zbw-revisions-modal').modal('hide');
          renderProps();
          renderOutline();
          reloadCanvas();
          alert('回滚已立即发布，线上已更新到该版本');
        } catch (e) {
          alert('回滚失败：' + e.message);
        }
      });
    });
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4" class="text-danger">加载失败：${esc(e.message)}</td></tr>`;
  }
});

document.getElementById('zbw-btn-publish').addEventListener('click', () => {
  if (!CAN_PUBLISH) { alert('当前账号没有发布权限（builder:publish）'); return; }
  document.getElementById('zbw-publish-note').value = '';
  $('#zbw-publish-modal').modal('show');
});

document.getElementById('zbw-publish-confirm').addEventListener('click', async () => {
  const btn = document.getElementById('zbw-publish-confirm');
  btn.disabled = true;
  try {
    await publishLayout();
    $('#zbw-publish-modal').modal('hide');
    alert('发布成功，线上已更新');
    saveStatus.textContent = '已发布';
    saveStatus.className = 'zbw-save-status saved';
  } catch (e) {
    alert('发布失败：' + e.message);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('zbw-btn-front').addEventListener('click', () => {
  window.open('/', '_blank');
});

/* ============================================================
 * 设备切换
 * ============================================================ */

document.querySelectorAll('[data-device]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-device]').forEach(b => b.classList.toggle('active', b === btn));
    iframe.classList.remove('device-tablet', 'device-mobile');
    if (btn.dataset.device !== 'desktop') {
      iframe.classList.add('device-' + btn.dataset.device);
    }
  });
});

/* ============================================================
 * iframe 消息
 * ============================================================ */

window.addEventListener('message', e => {
  const d = e.data;
  if (!d || d.source !== 'zbw-preview') return;
  if (d.type === 'ready') {
    if (state.selectedId) {
      iframe.contentWindow.postMessage(
        { target: 'zbw-preview', type: 'select', id: state.selectedId }, '*');
    }
    renderOutline();
  }
  if (d.type === 'select') {
    state.selectedId = d.id;
    renderProps();
    renderOutline();
  }
  if (d.type === 'drop') {
    const p = d.payload || {};
    if (p.kind === 'new' && p.widgetType) {
      const w = state.widgets.get(p.widgetType);
      if (!w || w.enabled === false) return;
      addWidget(p.widgetType, d.parentId === '__root__' ? null : d.parentId, d.index);
    } else if (p.kind === 'move' && p.nodeId) {
      moveNode(p.nodeId, d.parentId, d.index);
    }
  }
});

/* 离开页面前未保存提示 */
window.addEventListener('beforeunload', e => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

/* ============================================================
 * 启动
 * ============================================================ */

async function bootstrap() {
  const data = await api(API.page);
  state.scope = data.page.scope;
  state.layout = data.layout || { version: 1, root: [] };

  const [catData, colData] = await Promise.all([
    api(API.widgets + '?scope=' + state.scope),
    api(API.columns).catch(() => ({ columns: [] })),
  ]);
  state.catalog = catData.categories;
  state.listColumns = colData.columns || [];
  for (const list of Object.values(state.catalog)) {
    for (const w of list) state.widgets.set(w.type, w);
  }
  renderCatalog();
  renderProps();
  renderOutline();
  iframe.src = PREVIEW_URL;
}

bootstrap().catch(err => {
  document.querySelector('.zbw-canvas-wrap').innerHTML =
    `<div class="alert alert-danger m-3">编辑器初始化失败：${esc(err.message)}</div>`;
});
