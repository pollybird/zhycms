# 发布流程（RELEASE Checklist）

本文件是 ZhyCMS 每次版本发布的标准操作清单。逐项确认后再提交 tag。

## 一、版本号一致性

- [ ] `app/models/setting.py` 中 `CMS_VERSION = 'X.Y.Z'`
- [ ] `plugins/*/manifest.json` 的 `version` 与 Plugin 类 `version` 属性一致
- [ ] `CHANGELOG.md` 顶部 `## [X.Y.Z] - YYYY-MM-DD` 且日期 ≤ 今天
- [ ] `README.md` 含 `当前版本：vX.Y.Z`
- [ ] `wiki.html` `<title>` 与徽标含 `vX.Y.Z`
- [ ] 执行 `python scripts/check_release.py --version vX.Y.Z` 全绿

## 二、迁移检查

- [ ] `flask db heads` 单头
- [ ] 新增迁移在 sqlite + MySQL 双库空跑无异常
- [ ] `UPGRADE.md` 已补该版本升级章节

## 三、翻译

- [ ] `pybabel extract/update` 后无 fuzzy 拋留
- [ ] 删除 `.mo` 文件重启应用，自动重新生成成功

## 四、文档

- [ ] `CHANGELOG.md`（Features / Fixed / Upgrade 三段）
- [ ] `UPGRADE.md` 已更新
- [ ] `README.md` 版本速览已更新
- [ ] `wiki.html` 已更新
- [ ] 两平台 Wiki（Gitee / GitHub）已同步
- [ ] `CONTRIBUTING.md` 测试章节已更新（如涉及测试流程变化）

## 五、测试

- [ ] `pytest` 全绿
- [ ] `python scripts/check_constants.py` 零违规
- [ ] 手工冒烟清单：
  - [ ] 安装向导走通（全新库）
  - [ ] 建站 → 文章 CRUD → 搜索 → 插件启停 → 备份恢复
  - [ ] 中英文切换无残留

## 六、提交与标签

- [ ] commit 消息含版本号
- [ ] `git tag vX.Y.Z`
- [ ] `git push origin main --tags`
- [ ] `git push github main --tags`（GitHub 如需代理：`git -c http.https://github.com/.proxy= push github main --tags`）
- [ ] 两平台 Release / 发行版附 CHANGELOG 摘录

## 七、发布后验证

- [ ] 拉取 tag 全新目录空库安装向导走通
- [ ] 旧库升级路径（UPGRADE 章节）走通
- [ ] GitHub Actions CI 全绿
