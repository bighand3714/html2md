# html2md

将 Wiki 类 HTML 页面转换为 Obsidian 兼容的 Markdown 文档。

## 安装

```bash
pip install -e .
```

## 使用

```bash
# 转换本地 HTML 文件
html2md convert page.html

# 转换 URL（自动下载 HTML 并转换）
html2md convert https://en.wikipedia.org/wiki/Metal_Gear_Solid

# 批量转换
html2md convert test/*.html --output output/

# 手动指定站点策略
html2md convert page.html --strategy fandom

# 严格模式（遇错即停）
html2md convert page.html --strict

# 列出可用站点策略
html2md list-strategies
```

## 支持的站点

| 站点 | 策略标识 | 
|------|----------|
| Wikipedia English | `wikipedia_en` |
| Wikipedia Japanese | `wikipedia_jp` |
| Fandom Wiki | `fandom` |
| ZeldaWiki | `zeldawiki` |

策略配置文件在 `sites/` 目录，可自行扩展。

## 转换效果

- **引用角标**：数字角标转为 Obsidian `[^ref_N]` footnote，点击可跳转
- **字母角标**：保留为 `[a]` `[b]` 纯文本显示
- **图片**：外部图片保留原始 URL 链接；base64 图片提取到 `img/` 目录
- **表格**：合并单元格自动拆分；信息框（Infobox）保留为 Markdown 表格
- **链接**：Wiki 内部链接保留完整 URL
- **目录**：自动移除
- **导航模板**：自动移除

## 项目结构

```
html2md/
├── src/html2md/
│   ├── cli.py          # CLI 入口
│   ├── pipeline.py     # 转换流水线
│   ├── downloader.py   # URL 下载
│   ├── extractor.py    # 页面清洗
│   ├── converter.py    # HTML → MD
│   ├── citations.py    # 引用系统
│   ├── tables.py       # 表格处理
│   ├── images.py       # 图片处理
│   ├── strategy.py     # 站点策略
│   ├── obsidian.py     # Obsidian 格式工具
│   └── errors.py       # 错误处理
├── sites/              # 站点策略配置
├── tests/              # 单元测试
└── docs/               # 需求文档
```

## 测试

```bash
pytest
```

## 依赖

- Python >= 3.11
- beautifulsoup4 + lxml
- requests
- PyYAML
