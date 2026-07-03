# html2md — 术语表

## 输入

- **本地 HTML 文件**：用户通过浏览器"另存为"或其他方式保存到磁盘的完整 HTML 页面。路径可直接传入 CLI。
- **远程 URL**：Wiki 页面的网络地址。CLI 接收后先下载 HTML，再执行与本地文件相同的转换流程。

## 输出

- **MD 文档**：转换后的 Obsidian 兼容 Markdown 文件。文件名与源 HTML 同名（扩展名不同）。默认输出到源 HTML 同目录。

## 域概念

- **角标（Footnote Reference / Superscript）**：正文中位于语句末尾的上标标记。Wiki 页面有两种：数字角标（指向 References）和字母角标（指向 Notes）。
- **Notes**：Wiki 页面中的说明性注释，角标使用字母（a, b, c, d...）。正文中往往紧跟在某个语句后面。在 MD 中位于 `## Notes` section。
- **References**：Wiki 页面中的正式引用来源，角标使用数字（1, 2, 3...）。在 MD 中位于 `## References` section。
- **Footnote**：Obsidian 的 `[^id]` + `[^id]: content` 语法。支持正文与底部之间的双向跳转。Notes 和 References 分别转换为独立的 footnote 组。
- **Footnote ID 命名**：Notes 组使用 `note_` 前缀 + 角标显示字母（如 `[^note_a]`）；References 组使用 `ref_` 前缀 + 角标显示数字（如 `[^ref_1]`）。仅为 Obsidian 内部标识，不在页面上直接显示。

## 页面元素

- **Infobox / 信息框**：Wiki 页面右侧的摘要表格（Developer、Publisher、Release Date 等）。转换为普通 Markdown 表格。
- **Navbox / 导航模板**：页面底部的系列导航框。在转换时删除。
- **Hatnote / 消歧义提示**：页面顶部的引导说明（如 "For the X, see Y"）。保留为斜体文本 + 链接。
- **Main article 引导链接**：段落开头的 "Main article: XXX" 链接。保留为普通文本链接。
- **TOC / 目录**：页面自动生成的内容目录。在转换时删除。

## 站点策略

- **站点策略（Site Strategy）**：定义如何从特定 Wiki 站点的 HTML 中提取和转换内容的配置。包含内容选择器、引用系统规则、特殊元素处理方式等。以 YAML 文件保存。
- **站点检测（Site Detection）**：自动判断输入属于哪个已配置站点的过程。URL 输入按域名匹配，本地文件按 HTML Meta 标签匹配。失败时提示用户手动指定。
- **内置策略**：工具预置的四种 Wiki 站点策略（Wikipedia EN、Wikipedia JP、Fandom、ZeldaWiki），无需用户额外配置即可使用。
