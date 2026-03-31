# Deepfreeze Kibana Plugin

A Kibana plugin that provides a native UI for Deepfreeze operations. Acts as a thin wrapper around the Deepfreeze service — all business logic stays in the service.

## Architecture

```
Browser (Kibana UI) → Kibana Server Plugin (proxy) → Deepfreeze Service
```

- Browser never talks directly to the Deepfreeze service
- All requests proxy through Kibana server routes at `/api/deepfreeze/*`
- Auth token stored in `kibana.yml`, not exposed to browser
- SSE events relayed through Kibana server

## Configuration

Add to `kibana.yml`:

```yaml
xpack.deepfreeze:
  enabled: true
  serviceUrl: "http://deepfreeze-host:8000"
  serviceToken: "df_tok_..."   # Optional
```

## Pages

| Page | Description |
|------|-------------|
| Overview | Dashboard with cluster health, repo stats, active jobs |
| Repositories | Repository browser with search, sort, detail flyout |
| Thaw Requests | Thaw request list with progress tracking, refreeze action |
| Actions | Thaw, Rotate, Refreeze, Cleanup, Repair launchers |
| Scheduler | Scheduled job management (add/edit/pause/resume/delete) |
| Activity | Audit log with detail flyout |

## Development

```bash
# Build the plugin
cd packages/deepfreeze-kibana
yarn build

# Run Kibana in dev mode with the plugin
yarn start --plugin-path packages/deepfreeze-kibana
```

## Target Versions

- **Primary**: Kibana 8.x (tested on 8.19.13)
- **Secondary**: Kibana 9.x (adapt before completion)

## Known Issues

### React error #301 on Repositories and Thaw Requests pages (Kibana 8.19.13)

**Error**: `Minified React error #301` ("Rendered more hooks than during the previous render")

**Affected pages**: Repositories, Thaw Requests (and possibly Actions, Scheduler, Activity)

**Working**: Overview page renders correctly.

**Status**: Unresolved. Attempted fixes:
- Moved `useStatus` initial fetch from render body into `useEffect` (correct pattern, did not resolve)
- Added `<EuiProvider>` wrapper in `renderApp` (required by EUI v104, did not resolve)

**Suspected cause**: The plugin bundles with esbuild in CJS format wrapped in a custom `__kbnBundles__` IIFE. The complex EUI components used on these pages (`EuiBasicTable`, `EuiFlyout`, `EuiDatePicker`, `EuiGlobalToastList`, `EuiSuperSelect`) may be interacting with the custom `require()` shim or the React instance from `__kbnSharedDeps__` in a way that causes hook ordering inconsistencies across renders. The root cause likely lies in the bundle format — a proper Kibana build system (webpack + `@kbn/optimizer`) would handle this correctly.

**Possible next steps**:
- Switch to `--jsx=automatic` in esbuild (uses `react/jsx-runtime` instead of `React.createElement`)
- Audit esbuild output to verify all pages are importing the same React instance
- Investigate whether `__kbnSharedDeps__.React` behaves differently in calls from complex EUI component internals
- Consider using Kibana's official `@kbn/optimizer` build pipeline instead of a hand-rolled esbuild script
