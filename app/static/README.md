# 静态资源目录

前端资源由 CDN 加载（Bootstrap 4 + AdminLTE 3 + FontAwesome + CKEditor 5）。

`uploads/` 子目录存放用户上传的文件，按模块和日期自动分目录：

```
uploads/
  column/      栏目自定义字段文件
  article/     文章封面与字段文件
  fragment/    碎片字段文件
  friend_link/ 友情链接 LOGO
  site/        网站 LOGO
  form/        表单提交的附件
  common/      其他通用上传
```
