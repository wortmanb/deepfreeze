/**
 * Build script for the Deepfreeze Kibana plugin.
 *
 * Produces: build/deepfreeze-{kibanaVersion}.zip
 * Install:  kibana-plugin install file:///path/to/deepfreeze-{version}.zip
 *
 * Bundle format notes:
 *  - Server bundle: plain CJS (Node.js loads it)
 *  - Public bundle: must call __kbnBundles__.define('plugin/deepfreeze/public', ...)
 *    and must live at target/public/deepfreeze.plugin.js
 *    Shared npm packages (React, EUI, etc.) are exposed by Kibana under
 *    window.__kbnSharedDeps__.*  (see @kbn/ui-shared-deps-src/src/definitions.js)
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


// -- Step 2: Bundle client-side code --
console.log('  Bundling client-side code...');

// Build with esbuild to a temp CJS file first, then wrap it in Kibana's
// __kbnBundles__ registration format. Kibana exposes shared npm packages
// (React, EUI, etc.) through window.__kbnSharedDeps__; we intercept the
// require() calls esbuild emits and map them to those globals.

const tmpPublicPath = resolve(BUILD, 'tmp_public.js');

try {
  execSync(`npx esbuild public/index.ts \
    --bundle \
    --outfile=${tmpPublicPath} \
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
    --external:@emotion/react \
    --external:@emotion/cache \
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

// Wrap esbuild CJS output in Kibana's plugin bundle format.
// Kibana discovers this file at:  <plugin>/target/public/deepfreeze.plugin.js
// and loads it via:  __kbnBundles__.get('plugin/deepfreeze/public').plugin()
const esbuildBundle = readFileSync(tmpPublicPath, 'utf8');
const kibanaBundle = `(function () {
  var module = { exports: {} };
  var exports = module.exports;

  // Expose React/ReactDOM as locals so JSX compiled with the classic transform
  // (React.createElement calls) works even in files that don't import React.
  var S = typeof __kbnSharedDeps__ !== 'undefined' ? __kbnSharedDeps__ : {};
  var React    = S.React;
  var ReactDOM = S.ReactDom;

  // Map external require() calls (emitted by esbuild) to Kibana's shared deps.
  // Kibana exposes all shared npm packages under window.__kbnSharedDeps__.*
  // See: @kbn/ui-shared-deps-src/src/definitions.js
  function require(id) {
    var sharedMap = {
      'react':            S.React,
      'react-dom':        S.ReactDom,
      'react-router-dom': S.ReactRouterDom,
      '@elastic/eui':     S.ElasticEui,
      '@elastic/datemath': S.KbnDatemath,
      '@emotion/react':   S.EmotionReact,
      '@emotion/cache':   S.EmotionCache,
      'moment':           S.Moment,
    };
    if (Object.prototype.hasOwnProperty.call(sharedMap, id)) {
      return sharedMap[id];
    }
    // @kbn/* imports that reach here are type-only; return empty object.
    return {};
  }

${esbuildBundle}

  // Register with Kibana's plugin loader.
  // get('plugin/deepfreeze/public') returns module.exports, which has { plugin: fn }
  __kbnBundles__.define('plugin/deepfreeze/public', function () {
    return module.exports;
  }, 0);
})();
`;

mkdirSync(resolve(TARGET, 'target', 'public'), { recursive: true });
writeFileSync(resolve(TARGET, 'target', 'public', 'deepfreeze.plugin.js'), kibanaBundle);
rmSync(tmpPublicPath, { force: true });
console.log('  Client bundle wrapped for Kibana.');


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
