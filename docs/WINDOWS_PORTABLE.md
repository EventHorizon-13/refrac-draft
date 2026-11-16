# RefracDraft Windows x64 便携版

解压下载的 `RefracDraft-Windows-x64-portable` 构建产物后，双击 `RefracDraft.exe`。请保留整个解压目录；`_internal` 内含 Python/Qt 运行文件及参考 DXF/PDF，不能只复制 EXE。

程序从 Excel 或 JSON 导入模块、夹板、锚固件参数。修改参数后点击「生成预览」，再用工具栏导出 DXF 或 PDF。DXF/PDF 的保存位置由文件对话框选择。示例文件已随程序打包，不依赖当前工作目录。

该构建在 Windows x64 GitHub Actions 环境中完成，并使用便携版程序本身执行一次 B2 示例生成、DXF 重读和 PDF 矢量检查。它仍是 Phase 1 开发预览版；异形组合、锚固件和开口定义、全部黄金样板逐页比对及 Windows 人工交互验收尚未完成，不应直接作为生产加工图验收依据。

源码、问题与更新：[EventHorizon-13/refrac-draft](https://github.com/EventHorizon-13/refrac-draft)。

