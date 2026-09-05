// 将本地静态预览转换为 GitHub Pages 可部署版本。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pagePath = path.join(root, 'docs', 'index.html');
let html = fs.readFileSync(pagePath, 'utf8');

html = html
  .replaceAll('href="/ct-', 'href="./public/ct-')
  .replaceAll('href="/qions-', 'href="./public/qions-')
  .replaceAll('src="/public/', 'src="./public/')
  .replaceAll("url('/public/", "url('./public/")
  .replace('src="/tmp/preview/client.js"', 'src="./client.js"')
  .replaceAll('href="/review"', 'href="#demo"')
  .replaceAll('href="/agent"', 'href="#demo"')
  .replaceAll('href="/evaluation"', 'href="https://github.com/wxy11117/LungSight/tree/main/tests"')
  .replace('进入 Agent <span>↗</span>', '查看演示 <span>↓</span>')
  .replace(
    '<button class="run-button"><span>运行真实模型分析</span><i>→</i></button>',
    '<a class="run-button" href="#app-download"><span>下载桌面端运行真实模型</span><i>↓</i></a>',
  );

fs.writeFileSync(pagePath, html, 'utf8');
const clientPath = path.join(root, 'docs', 'client.js');
const client = fs.readFileSync(clientPath, 'utf8').replaceAll("'/public/", "'./public/");
fs.writeFileSync(clientPath, client, 'utf8');
fs.writeFileSync(path.join(root, 'docs', '.nojekyll'), '', 'utf8');
