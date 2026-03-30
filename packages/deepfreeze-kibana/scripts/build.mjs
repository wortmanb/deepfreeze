/**
 * Build script for the Deepfreeze Kibana plugin.
 *
 * Produces: build/deepfreeze-{kibanaVersion}.zip
 * Install:  kibana-plugin install file:///path/to/deepfreeze-{version}.zip
 *
 * Uses esbuild for both server and client compilation — fast, no tsc
 * version compatibility issues, and handles .ts imports correctly.
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


// -- Step 1: Bundle server entry point --
console.log('  Bundling server...');

// Bundle server/index.ts into a single file. @kbn/* packages are
// externals resolved by Kibana at runtime. Everything else (our own
// modules, common/) gets inlined into the bundle.
try {
  execSync(`npx esbuild server/index.ts \
    --bundle \
    --outfile=${resolve(TARGET, 'server', 'index.js')} \
    --format=cjs \
    --platform=node \
    --target=node18 \
    --external:@kbn/* \
    --resolve-extensions=.ts,.tsx,.js,.json \
    --log-level=warning`, {
    stdio: 'inherit',
    cwd: ROOT,
  });
} catch {
  console.error('Server bundle failed');
  process.exit(1);
}

// -- Step 1b: Bundle common (for any direct requires) --
console.log('  Bundling common...');
try {
  execSync(`npx esbuild common/index.ts \
    --bundle \
    --outfile=${resolve(TARGET, 'common', 'index.js')} \
    --format=cjs \
    --platform=node \
    --target=node18 \
    --resolve-extensions=.ts,.tsx,.js,.json \
    --log-level=warning`, {
    stdio: 'inherit',
    cwd: ROOT,
  });
} catch {
  console.error('Common bundle failed');
  process.exit(1);
}

// -- Step 2: Bundle client-side code --
console.log('  Bundling client-side code...');

// Client is bundled into a single file. @kbn/*, React, EUI, moment
// are all externals provided by Kibana at runtime.
try {
  execSync(`npx esbuild public/index.ts \
    --bundle \
    --outfile=${resolve(TARGET, 'public', 'index.js')} \
    --format=cjs \
    --platform=browser \
    --target=es2020 \
    --loader:.tsx=tsx \
    --jsx=transform \
    --resolve-extensions=.ts,.tsx,.js,.json \
    --external:@kbn/* \
    --external:react \
    --external:react-dom \
    --external:react-router-dom \
    --external:@elastic/eui \
    --external:@elastic/datemath \
    --external:@emotion/* \
    --external:moment \
    --define:process.env.NODE_ENV='"production"' \
    --log-level=warning`, {
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
manifest.kibanaVersion = KIBANA_VERSION;
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
