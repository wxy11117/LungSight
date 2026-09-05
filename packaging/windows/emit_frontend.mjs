import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
const [root, outDir] = process.argv.slice(2);
const {emitStandaloneOutput} = await import(pathToFileURL(path.join(root, 'node_modules/vinext/dist/build/standalone.js')));
console.log(JSON.stringify(emitStandaloneOutput({root, outDir, vinextPackageRoot:fs.realpathSync(path.join(root, 'node_modules/vinext'))})));
