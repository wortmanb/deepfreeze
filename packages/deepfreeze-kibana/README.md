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

- **Primary**: Kibana 8.x
- **Secondary**: Kibana 9.x (adapt before completion)
