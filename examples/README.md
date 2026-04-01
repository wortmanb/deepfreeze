# Deepfreeze Examples

This directory contains example configuration files for scheduling automatic deepfreeze rotation.

## Files

| File | Description |
|------|-------------|
| `config.yml.example` | sanitized example CLI configuration |
| `deepfreeze-rotate.service` | systemd service unit for running rotation |
| `deepfreeze-rotate.timer` | systemd timer for scheduling rotation |
| `crontab-example.txt` | crontab examples for various scheduling options |

## Before You Deploy These Examples

- Copy `config.yml.example` to a private path such as `~/.deepfreeze/config.yml` or `/etc/deepfreeze/config.yml`
- Restrict the config file with `chmod 600`
- Do not commit credentials, API keys, or cloud secrets into the config file
- Prefer workload identity or instance roles over long-lived static cloud credentials

## systemd (Recommended)

For systems using systemd, use the service and timer files together:

```bash
# Copy files to systemd directory
sudo cp deepfreeze-rotate.service /etc/systemd/system/
sudo cp deepfreeze-rotate.timer /etc/systemd/system/

# Install a config file with restricted permissions
sudo install -d -m 0750 /etc/deepfreeze
sudo install -m 0600 config.yml.example /etc/deepfreeze/config.yml

# Edit the service file to adjust paths, user, and optional environment file
sudo vim /etc/systemd/system/deepfreeze-rotate.service

# Enable and start the timer
sudo systemctl daemon-reload
sudo systemctl enable --now deepfreeze-rotate.timer

# Verify timer is active
systemctl list-timers deepfreeze-rotate.timer
```

### Manual Run

```bash
sudo systemctl start deepfreeze-rotate.service
```

### View Logs

```bash
journalctl -u deepfreeze-rotate.service
```

## cron

For systems using cron, see `crontab-example.txt` for supported scheduling options.
Avoid embedding raw credentials in crontab entries.

```bash
# Edit user crontab
crontab -e

# Add the line (runs 1st of every month at 2 AM):
0 2 1 * * /usr/local/bin/deepfreeze --config /etc/deepfreeze/config.yml rotate --keep 6
```

## Configuration

Before using these examples, ensure:

1. Deepfreeze is installed and accessible at the path specified (default: `/usr/local/bin/deepfreeze`)
2. Configuration file exists at the specified path (default: `/etc/deepfreeze/config.yml`)
3. The user running the service has appropriate permissions and cloud access configured
4. If you use an environment file, it is root-owned and mode `0600`
