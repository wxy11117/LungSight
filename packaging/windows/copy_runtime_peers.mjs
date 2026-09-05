// standalone 清单不包含运行期 peer dependencies，显式补齐并递归拷贝其直接依赖。
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const [root,target]=process.argv.slice(2);
const seen=new Set();
function copy(name,resolver) {
  if(seen.has(name)) return;
  const source=path.dirname(fs.realpathSync(resolver.resolve(name+'/package.json')));
  const pkg=JSON.parse(fs.readFileSync(path.join(source,'package.json'),'utf8'));
  const dest=path.join(target,'node_modules',name);
  fs.cpSync(source,dest,{recursive:true,dereference:true,filter:p=>!path.relative(source,p).split(path.sep).includes('node_modules')});
  seen.add(name);
  for(const dep of Object.keys(pkg.dependencies??{})) copy(dep,createRequire(path.join(source,'package.json')));
}
for(const name of ['react','react-dom','react-server-dom-webpack']) copy(name,createRequire(path.join(root,'package.json')));
console.log('Runtime peers: '+[...seen].join(', '));
