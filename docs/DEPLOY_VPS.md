# Deploying BAS Assistant To a VPS

Current standard production shape:

- BAS Assistant launched by `scripts/start_production.sh`
- bound to `127.0.0.1:8000`
- Nginx reverse proxy on `80/443`
- persistent runtime state in `data/`, `output/`, `uploads/`, and `logs/`
- app auth enabled with bootstrap admin credentials and session-based login

Note:
Docker artifacts still exist in the repo for local and alternate deployment use, but the reviewed VPS path is the direct `uvicorn` runtime behind Nginx.

## Prerequisites

- Ubuntu 22.04 or 24.04 VPS
- A DNS record pointing your domain or subdomain to the VPS
- SSH access with a sudo-capable user

## 1. Install Runtime Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx apache2-utils
sudo systemctl enable --now nginx
```

## 2. Copy the project to the server

Example target location:

```bash
mkdir -p ~/apps
cd ~/apps
git clone <your-repo-url> bas-assistant
cd bas-assistant
mkdir -p data output uploads logs
```

## 3. Configure runtime environment

```bash
cp config/bas-assistant.env.example config/bas-assistant.env
nano config/bas-assistant.env
mkdir -p logs data output uploads
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

Set at minimum:

- `BAS_SESSION_SECRET`
- `BAS_DATABASE_URL`
- `BAS_BOOTSTRAP_ADMIN_PASSWORD`

## 4. Start the application

Use the bundled production launcher:

```bash
./scripts/start_production.sh
```

In another shell:

```bash
curl http://127.0.0.1:8000/healthz
```

If you want the process to survive shell exit, run it under `systemd` as described below.

Initialize the database schema if needed:

```bash
.venv/bin/alembic upgrade head
```

## 5. Configure Nginx

Copy the example config and set your real domain:

```bash
sudo cp deploy/nginx.bas-assistant.conf.example /etc/nginx/sites-available/bas-assistant
sudo nano /etc/nginx/sites-available/bas-assistant
```

Change:

- `server_name bas.example.com;`

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/bas-assistant /etc/nginx/sites-enabled/bas-assistant
sudo nginx -t
sudo systemctl reload nginx
```

## 6. Add TLS

```bash
sudo certbot --nginx -d bas.example.com
```

After that, the app should be available at:

```text
https://bas.example.com
```

## 7. Add access control

The BAS Assistant UI now includes built-in authentication, but you should still protect the public edge.

Recommended options:

- Keep BAS auth enabled for application users
- Restrict by IP in Nginx where practical
- Put it behind Cloudflare Access or Tailscale for administrative deployments

Optional extra layer: Nginx basic auth.

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-bas-assistant yourusername
```

Then uncomment these lines in the nginx config:

```nginx
auth_basic "Restricted";
auth_basic_user_file /etc/nginx/.htpasswd-bas-assistant;
```

Reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Better options:

- Restrict by IP in Nginx
- Put it behind Cloudflare Access or Tailscale
- Run it on a private VPN-only host

## 8. Recommended systemd service

```bash
sudo cp deploy/bas-assistant.service.example /etc/systemd/system/bas-assistant.service
sudo systemctl daemon-reload
sudo systemctl enable --now bas-assistant.service
sudo systemctl status bas-assistant.service --no-pager
```

## 9. Updating the deployment

```bash
cd ~/apps/bas-assistant
git pull
.venv/bin/pip install -e .
sudo systemctl restart bas-assistant.service
```

## 10. Logs and troubleshooting

Application logs:

```bash
tail -f logs/bas-assistant.log
```

Nginx logs:

```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

Health checks:

```bash
curl http://127.0.0.1:8000/healthz
curl -I https://bas.example.com
```

## 11. Automated GitHub Checkpoints

The repo includes three checkpoint helpers:

- Manual push: `./scripts/push_checkpoint.sh`
- Safe auto-push wrapper: `./scripts/push_checkpoint_safe.sh`
- Cron installer: `./scripts/install_checkpoint_cron.sh`

Manual examples:

```bash
./scripts/push_checkpoint.sh
./scripts/push_checkpoint.sh --skip-tests --message "Manual checkpoint before parser refactor"
```

The safe wrapper runs the focused regression suite before commit/push and skips overlapping runs using `flock`.

Install the 30-minute cron job:

```bash
chmod +x scripts/push_checkpoint.sh scripts/push_checkpoint_safe.sh scripts/install_checkpoint_cron.sh
./scripts/install_checkpoint_cron.sh
```

Checkpoint cron logs:

```bash
tail -f logs/checkpoint_cron.log
```

If you need to customize the test gate for automated checkpoints:

```bash
export BAS_CHECKPOINT_TEST_CMD=".venv/bin/pytest tests/test_auth_and_database.py"
```

An example crontab entry is provided at `deploy/checkpoint_push.cron.example`.

## Notes

- Persistent app data is stored in `./data`.
- Generated reports, graphics, exports, and other artifacts are stored in `./output`.
- If you want the app reachable without Nginx, you can use `docker-compose.vultr.yml`, but that exposes the service directly on port `80` and is not the preferred setup.
