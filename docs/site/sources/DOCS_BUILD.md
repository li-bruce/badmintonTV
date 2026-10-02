# 框架手册的Markdown与网页

内容源是docs内的Markdown；`scripts/docs/build.mjs`生成`docs/site/`，提交生成产物便于直接离线阅读和平台静态托管。不要单独修改生成的HTML。

使用本机已提供的隔离Node工具runtime与Marked 17.0.5，无需给全局或模型Python装库：

```powershell
& C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe scripts/docs/build.mjs --marked-module C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/marked/lib/marked.esm.js
```

其它环境可在独立工具目录安装`marked@17.0.5`并传入其模块绝对路径，或通过`BTV_DOCS_MARKED_MODULE`指定。升级解析器须重新验证后修改版本约束。本次未新增安装。

构建7份核心页面，包含文档导航、当前页章节搜索、目录、窄屏和打印样式。没有浏览器外部依赖。Markdown原始HTML按文字显示；链接只允许http(s)、内部锚点与受控相对引用；文档不执行脚本。Mermaid代码保留在可展开的源码块中，主使用手册采用无需图形库的流程表与步骤。

`build-manifest.json`保存解析器版本和每份输入/输出hash。其它被引用的docs内Markdown作为source副本提供；不把仓库代码、D:/video或任意本地路径发布成网页资源。

平台正在接入`/guide/`到`docs/site/`，完成集成后会提供`/guide`跳转或入口。框架首页为`index.html`；离线可直接打开。浏览器“打印/保存PDF”可输出当前完整文档，即使此前做过章节过滤。

构建先验证所有来源的真实路径、文件存在性和内容，再在新暂存目录生成完整集合。成功时替换整个site目录，使已撤下的引用不再残留；发布失败则恢复旧目录。输出目录为链接或目录外路径时拒绝写入。Windows两次目录改名之间存在极短的不可访问窗口，因此建议在静态阅读空闲时重建。

验收检查：七页能打开，导航与source下载存在；触球等关键词过滤后能清空恢复；窄屏没有整页横向溢出（宽表格在容器中横滚）；原HTML/危险协议不能执行；重复构建相同源得到相同内容hash。
