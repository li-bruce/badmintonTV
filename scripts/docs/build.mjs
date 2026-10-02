/** Build the local handbook from reviewed Markdown. No browser CDN or runtime dependency. */
import {readFile, writeFile, mkdir, realpath, lstat, mkdtemp, rename, rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const docs = path.join(root, 'docs');
const output = path.join(docs, 'site');
const realDocs = await realpath(docs);
const within = (parent, child) => {
  const relative = path.relative(parent, child);
  return relative !== '' && !relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative);
};
async function checkedSource(source) {
  const resolved = await realpath(source);
  if (!within(realDocs, resolved) || within(path.join(realDocs, 'site'), resolved) || !(await lstat(resolved)).isFile()) {
    throw new Error('Source must be a regular file inside docs: ' + source);
  }
  return resolved;
}
async function regularOutput() {
  try {
    const info = await lstat(output);
    if (info.isSymbolicLink() || !info.isDirectory() || await realpath(output) !== path.join(realDocs, 'site')) {
      throw new Error('Refusing nonlocal or linked output directory: ' + output);
    }
    return true;
  } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
const argument = process.argv.indexOf('--marked-module');
let modulePath = argument >= 0 ? process.argv[argument + 1] : process.env.BTV_DOCS_MARKED_MODULE;
if (!modulePath) {
  try { modulePath = createRequire(import.meta.url).resolve('marked'); }
  catch { throw new Error('Provide --marked-module /absolute/path/to/marked/lib/marked.esm.js (tested: marked 17.0.5).'); }
}
const {Marked} = await import(pathToFileURL(path.resolve(modulePath)).href);
const packageRoot = path.dirname(path.dirname(path.resolve(modulePath)));
const dependency = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
if (dependency.name !== 'marked' || dependency.version !== '17.0.5') {
  throw new Error('This build is pinned to marked 17.0.5; review and validate before updating the parser.');
}
const pages = [
  ['FRAMEWORK_GUIDE.md', 'index.html', '框架与使用手册', '01'],
  ['END_TO_END_CAPABILITY_PLAN.md', 'capabilities.html', '能力与论文路线', '02'],
  ['IMPLEMENTATION_ROUND_2026-10-02.md', 'implementation.html', '本轮开发计划', '03'],
  ['ANNOTATION_TOOLS_RESEARCH_2026-10-02.md', 'tools.html', '开源工具比较', '04'],
  ['ROUND_VALIDATION_2026-10-02.md', 'validation.html', '本轮验收记录', '05'],
  ['STAGE_ACCEPTANCE.md', 'stages.html', '长期阶段验收', '06'],
  ['QUICKSTART.md', 'quickstart.html', '启动与运行', '07'],
];
const pageMap = new Map(pages.map(([md, html]) => [path.resolve(docs, md), html]));
const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const textSource = async source => (await readFile(source, 'utf8')).replace(/\r\n?/g, '\n');
const copies = new Map();
const invalid = [];
function safeLink(href, source) {
  if (/^https?:\/\//i.test(href)) return href;
  if (href.startsWith('#')) return href;
  if (/^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith('//') || href.startsWith('/')) return null;
  const [relative, fragment] = href.split('#', 2);
  const destination = path.resolve(path.dirname(source), decodeURIComponent(relative));
  if (pageMap.has(destination)) return pageMap.get(destination) + (fragment ? '#' + fragment : '');
  // Only publish referenced Markdown inside docs. Source code and private data stay outside this site.
  if (destination.startsWith(docs + path.sep) && destination.endsWith('.md') && !destination.startsWith(output + path.sep)) {
    const rel = path.relative(docs, destination).split(path.sep).join('/');
    copies.set(destination, 'sources/' + rel);
    return 'sources/' + rel;
  }
  return null;
}
const css = await textSource(path.join(root, 'scripts/docs/handbook.css'));
const browserScript = await textSource(path.join(root, 'scripts/docs/handbook.js'));
await regularOutput();
const generated = new Map();
const manifest = {format:'badmintontv-handbook', schema_version:'1.0', parser:{name:dependency.name, version:dependency.version, license:dependency.license}, pages:[]};
for (const [filename, target, label] of pages) {
  const source = path.join(docs, filename);
  const markdown = await textSource(await checkedSource(source));
  const headings = [];
  const usedIds = new Map();
  const renderer = {
    html({text}) { return esc(text); },
    heading({tokens, depth, text}) {
      const base = text.replace(/<[^>]*>/g, '').replace(/[`*]/g, '').trim().toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-|-$/g, '') || 'section';
      const count = usedIds.get(base) || 0; usedIds.set(base, count + 1);
      const id = base + (count ? '-' + count : '');
      headings.push({depth, id, text:text.replace(/[`*]/g, '')});
      return `<h${depth} id="${esc(id)}">${this.parser.parseInline(tokens)}</h${depth}>\n`;
    },
    link({href, tokens}) {
      const destination = safeLink(href, source);
      const text = this.parser.parseInline(tokens);
      return destination ? `<a href="${esc(destination)}"${/^https?:/.test(destination) ? ' target="_blank" rel="noopener noreferrer"' : ''}>${text}</a>` : `<span class="local-reference" title="请在本地仓库查看">${text}</span>`;
    },
    image({href, text}) {
      const destination = safeLink(href, source);
      return destination ? `<a href="${esc(destination)}">${esc(text || '查看图片')}</a>` : esc(text);
    },
    table(token) {
      const cell = (item, tag) => `<${tag}>${this.parser.parseInline(item.tokens)}</${tag}>`;
      return `<div class="table-scroll" tabindex="0" aria-label="表格，可横向滚动"><table><thead><tr>${token.header.map(c=>cell(c,'th')).join('')}</tr></thead><tbody>${token.rows.map(r=>'<tr>'+r.map(c=>cell(c,'td')).join('')+'</tr>').join('')}</tbody></table></div>`;
    },
    code({text, lang}) {
      const block = `<pre><code>${esc(text)}</code></pre>`;
      return lang === 'mermaid' ? `<details class="diagram-source"><summary>查看流程定义（Mermaid源码）</summary>${block}</details>` : block;
    },
  };
  const parser = new Marked({gfm:true, breaks:false, async:false, renderer});
  const content = parser.parse(markdown);
  const groups = content.split(/(?=<h2\b)/);
  const body = groups.map((part, index) => `<section class="chapter" data-chapter="${index}">${part}</section>`).join('\n');
  const toc = headings.filter(h=>h.depth===2).map(h=>`<a href="#${esc(h.id)}">${esc(h.text)}</a>`).join('');
  const navigation = pages.map(([,html,title,number])=>`<a href="${html}"${html===target?' class="selected" aria-current="page"':''}><span>${number}</span>${esc(title)}</a>`).join('');
  const title = headings.find(h=>h.depth===1)?.text || label;
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="description" content="badmintonTV本地框架与数据集构建手册"><title>${esc(label)} · badmintonTV</title><style>${css}</style></head>
<body><a class="skip" href="#document">跳到正文</a><aside class="sidebar" id="navigation"><a class="brand" href="index.html"><span class="logo">b</span><span>badmintonTV<small>知识与操作手册</small></span></a><p class="nav-label">项目文档</p><nav aria-label="文档">${navigation}</nav><div class="sidebar-note"><b>以证据推进每一步</b><p>工具可用、数据可用、模型达标<br>分别验证，分别记录。</p><a class="launch" href="http://127.0.0.1:18080/training">打开训练工作台 ↗</a><a href="http://127.0.0.1:18080/">返回主工作台 ↗</a></div></aside>
<div class="shell"><header class="topbar"><button class="menu-toggle" aria-controls="navigation" aria-expanded="false">☰ 文档</button><span class="breadcrumb">项目手册 <span>/</span> ${esc(label)}</span><button id="print-button">打印 / 保存PDF</button></header><main id="document"><div class="document-meta"><span class="eyebrow">BUILD · ANNOTATE · UNDERSTAND</span><span class="version">Markdown内容源 · 本地阅读</span></div><div class="search-box"><label for="doc-search">查找当前文档</label><input id="doc-search" type="search" placeholder="输入触球、快照、模型、未知…" autocomplete="off"><span id="search-count" role="status" aria-live="polite"></span></div><div class="reading-grid"><article aria-label="${esc(title)}">${body}<p id="empty-result" hidden>没有匹配章节。换个关键词，或清空搜索查看全文。</p></article><aside class="toc"><p class="nav-label">本页目录</p><nav aria-label="章节">${toc}</nav></aside></div><footer><span>内容源：<a href="sources/${filename}" download>${filename}</a></span><span>SHA-256 ${digest(markdown).slice(0,12)} · <a href="#document">返回顶部 ↑</a></span></footer></main></div><script>${browserScript}</script></body></html>`;
  generated.set(target, html);
  copies.set(source, 'sources/' + filename);
  manifest.pages.push({source:filename, output:target, source_sha256:digest(markdown), html_sha256:digest(html), chapters:headings.filter(h=>h.depth===2).length});
}
for (const [source, relative] of copies) {
  try { generated.set(relative, await textSource(await checkedSource(source))); }
  catch (error) { invalid.push(path.relative(root, source) + ': ' + error.message); }
}
if (invalid.length) throw new Error('Missing source references: ' + invalid.join(', '));
generated.set('MARKED-LICENSE.txt', await textSource(path.join(packageRoot, 'LICENSE.md')));
generated.set('build-manifest.json', JSON.stringify(manifest, null, 2) + '\n');
// Validate everything before replacing the generated set; old removed sources must disappear too.
const staging = await mkdtemp(path.join(realDocs, '.site-build-'));
const backup = staging + '-previous';
let previousMoved = false;
let published = false;
async function removeTemporary(directory) {
  const resolved = await realpath(directory);
  if (!within(realDocs, resolved) || path.dirname(resolved) !== realDocs || !path.basename(resolved).startsWith('.site-build-')) {
    throw new Error('Refusing unexpected cleanup path: ' + resolved);
  }
  await rm(resolved, {recursive:true});
}
try {
  for (const [relative, content] of generated) {
    const destination = path.resolve(staging, relative);
    if (!within(staging, destination)) throw new Error('Unexpected output path: ' + relative);
    await mkdir(path.dirname(destination), {recursive:true});
    await writeFile(destination, content);
  }
  if (await regularOutput()) { await rename(output, backup); previousMoved = true; }
  try { await rename(staging, output); published = true; }
  catch (error) { if (previousMoved) {await rename(backup, output); previousMoved = false;} throw error; }
  if (previousMoved) await removeTemporary(backup);
} finally {
  if (!published) await removeTemporary(staging);
}
console.log(JSON.stringify({pages:manifest.pages.length, markdown_sources:copies.size, parser:manifest.parser, output}, null, 2));
