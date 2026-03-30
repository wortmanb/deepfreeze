/**
 * Build script for the Deepfreeze Kibana plugin.
 *
 * Produces: build/deepfreeze-{kibanaVersion}.zip
 * Install:  kibana-plugin install file:///path/to/deepfreeze-{version}.zip
 */

import { execSync } from 'child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const BUILD = resolve(ROOT, 'build');
const TARGET = resolve(BUILD, 'kibana', 'deepfreeze');

const KIBANA_VERSION = process.env.KIBANA_VERSION || '8.19.0';

console.log(`Building Deepfreeze Kibana plugin for Kibana ${KIBANA_VERSION}...`);

// Clean
if (existsSync(BUILD)) rmSync(BUILD, { recursive: true });
mkdirSync(TARGET, { recursive: true });

// -- Step 1: Compile server + common TypeScript --
console.log('  Compiling server + common TypeScript...');

const tsConfig = {
  compilerOptions: {
    target: 'ES2020',
    module: 'commonjs',
    moduleResolution: 'node',
    outDir: resolve(TARGET),
    rootDir: resolve(ROOT),
    declaration: false,
    strict: false,
    esModuleInterop: true,
    skipLibCheck: true,
    resolveJsonModule: true,
    baseUrl: resolve(ROOT),
    paths: {
      '@kbn/core/server': ['./typestubs/core/server'],
      '@kbn/core/public': ['./typestubs/core/public'],
      '@kbn/config-schema': ['./typestubs/config-schema'],
      '@kbn/logging': ['./typestubs/logging'],
    },
  },
  include: [
    resolve(ROOT, 'server', '**', '*.ts'),
    resolve(ROOT, 'common', '**', '*.ts'),
  ],
  exclude: [
    resolve(ROOT, 'typestubs', '**'),
  ],
};
writeFileSync(resolve(BUILD, 'tsconfig.build.json'), JSON.stringify(tsConfig, null, 2));

try {
  execSync(`npx tsc -p ${resolve(BUILD, 'tsconfig.build.json')}`, { stdio: 'inherit', cwd: ROOT });
} catch {
  console.error('Server/common compilation failed');
  process.exit(1);
}

// -- Step 2: Bundle client-side code with esbuild --
console.log('  Bundling client-side code...');

// @kbn/* and React/EUI are externals provided by Kibana at runtime.
try {
  execSync(`npx esbuild public/index.ts \
    --bundle \
    --outfile=${resolve(TARGET, 'public', 'index.js')} \
    --format=cjs \
    --platform=browser \
    --target=es2020 \
    --loader:.tsx=tsx \
    --jsx=transform \
    --external:@kbn/* \
    --external:react \
    --external:react-dom \
    --external:react-router-dom \
    --external:@elastic/eui \
    --external:@elastic/datemath \
    --external:@emotion/* \
    --external:moment \
    --define:process.env.NODE_ENV='"production"'`, {
    stdio: 'inherit',
    cwd: ROOT,
  });
} catch {
  console.error('Client bundle failed');
  process.exit(1);
}

// -- Step 3: Copy manifest + package.json --
console.log('  Copying manifest...');

const manifest = JSON.parse(readFileSync(resolve(ROOT, 'kibana.json'), 'utf8'));
manifest.version = KIBANA_VERSION;
writeFileSync(resolve(TARGET, 'kibana.json'), JSON.stringify(manifest, null, 2));

writeFileSync(resolve(TARGET, 'package.json'), JSON.stringify({
  name: 'deepfreeze',
  version: KIBANA_VERSION,
  kibana: { version: KIBANA_VERSION },
}, null, 2));

// -- Step 4: Create zip --
console.log('  Creating zip archive...');
const zipName = `deepfreeze-${KIBANA_VERSION}.zip`;
try {
  execSync(`cd ${BUILD} && zip -r ${zipName} kibana/`, { stdio: 'inherit' });
} catch {
  console.error('Zip creation failed');
  process.exit(1);
}

console.log(`\n✓ Built: build/${zipName}`);
console.log(`\nInstall with:`);
console.log(`  kibana-plugin install file://${resolve(BUILD, zipName)}`);
