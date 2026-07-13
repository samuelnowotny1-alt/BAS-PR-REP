# Deploying BAS Assistant To a VPS

This app already has a working Dockerfile and Compose setup. The safest production shape is:

- BAS Assistant in Docker
- bound to `127.0.0.1:8000`
- Nginx reverse proxy on `80/443`
- TLS via Let's Encrypt
- app auth enabled with bootstrap admin credentials and session-based login

## Prerequisites

- Ubuntu 22.04 or 24.04 VPS
- A DNS record pointing your domain or subdomain to the VPS
- SSH access with a sudo-capable user

## 1. Install Docker and Nginx

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx apache2-utils
sudo systemctl enable --now docker nginx
sudo usermod -aG docker "$USER"
```

Log out and back in after adding yourself to the `docker` group.

## 2. Copy the project to the server

Example target location:

```bash
mkdir -p ~/apps
cd ~/apps
git clone <your-repo-url> bas-assistant
cd bas-assistant
mkdir -p data output
```

## 3. Configure runtime environment

```bash
cp config/bas-assistant.env.example config/bas-assistant.env
nano config/bas-assistant.env
mkdir -p logs data output uploads
```

Set at minimum:

- `BAS_SESSION_SECRET`
- `BAS_DATABASE_URL`
- `BAS_BOOTSTRAP_ADMIN_PASSWORD`

## 4. Start the application container

The production compose file binds the app only to localhost:

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml ps
curl -I http://127.0.0.1:8000/
```

If that `curl` returns `200 OK`, the app is running.

You can also verify the new health endpoint:

```bash
curl http://127.0.0.1:8000/healthz
```

If you are running outside Docker, initialize the database schema with:

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

## 8. Optional systemd service for non-Docker deployments

If you want the FastAPI app managed directly by `systemd` instead of Docker:

```bash
sudo cp deploy/bas-assistant.service.example /etc/systemd/system/bas-assistant.service
sudo nano /etc/systemd/system/bas-assistant.service
sudo systemctl daemon-reload
sudo systemctl enable --now bas-assistant.service
sudo systemctl status bas-assistant.service --no-pager
```

Use the bundled startup script for manual verification:

```bash
./scripts/start_production.sh
```

## 9. Updating the deployment

```bash
cd ~/apps/bas-assistant
git pull
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

## 10. Logs and troubleshooting

Container logs:

```bash
docker compose -f deploy/docker-compose.prod.yml logs -f
```

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
curl -I http://127.0.0.1:8000/
curl -I https://bas.example.com
```

## Notes

- Persistent app data is stored in `./data`.
- Generated reports, graphics, exports, and other artifacts are stored in `./output`.
- If you want the app reachable without Nginx, you can use `docker-compose.vultr.yml`, but that exposes the service directly on port `80` and is not the preferred setup.
