# Accomplishments Tracker

A small Flask app for logging work accomplishments throughout the year — categorized, tagged with impact, optionally with file attachments. Exports to Markdown for pasting into quarterly and yearly self-reviews.

## Local development

```bash
# Clone and enter the project
cd accomplishments

# Create a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize the database (creates accomplishments.db)
flask --app app init-db

# Run the dev server
flask --app app run --debug
```

Open http://127.0.0.1:5000 — add a few entries to test.

## Deploying to a DigitalOcean droplet

This guide assumes Ubuntu 24.04 on a $6/month droplet (1GB RAM, 25GB SSD). It walks through the whole setup. Where it says `your-domain.com` or `youruser`, substitute your own values.

### 1. Initial server setup

After creating the droplet, SSH in as root, then:

```bash
# Create a non-root user for yourself
adduser youruser
usermod -aG sudo youruser

# Set up SSH for the new user (from your local machine)
# ssh-copy-id youruser@your-droplet-ip

# Enable a basic firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# Update packages
apt update && apt upgrade -y
```

Log out and back in as `youruser` from now on.

### 2. Install dependencies

```bash
sudo apt install -y python3 python3-venv python3-pip sqlite3 git
```

### 3. Create the app user and clone the code

A dedicated user means the app runs with limited permissions.

```bash
sudo adduser --system --group --home /home/accomplishments accomplishments
sudo mkdir -p /home/accomplishments/app
sudo chown accomplishments:accomplishments /home/accomplishments/app

# Push your code to GitHub, then:
sudo -u accomplishments git clone https://github.com/YOU/accomplishments.git /home/accomplishments/app
```

### 4. Set up the virtualenv

```bash
cd /home/accomplishments/app
sudo -u accomplishments python3 -m venv .venv
sudo -u accomplishments .venv/bin/pip install -r requirements.txt
```

### 5. Create the .env file

```bash
sudo -u accomplishments tee /home/accomplishments/app/.env > /dev/null <<EOF
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
EOF
sudo chmod 600 /home/accomplishments/app/.env
```

### 6. Initialize the database

```bash
cd /home/accomplishments/app
sudo -u accomplishments .venv/bin/flask --app app init-db
sudo -u accomplishments mkdir -p uploads
```

### 7. Install the systemd service

```bash
sudo cp deploy/accomplishments.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now accomplishments
sudo systemctl status accomplishments  # confirm it's running
```

The app is now running on `127.0.0.1:8000` (not yet reachable from the internet).

### 8. Install Caddy as the reverse proxy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

### 9. Configure Caddy

Point your domain's A record to your droplet's IP first (DNS propagation can take a few minutes), then:

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile  # change example.com to your domain
sudo systemctl reload caddy
```

Caddy automatically obtains an HTTPS certificate from Let's Encrypt. Visit https://your-domain.com — you should see the app.

### 10. Set up nightly backups

```bash
sudo chmod +x /home/accomplishments/app/deploy/backup.sh
sudo -u accomplishments crontab -e
```

Add this line:

```
0 3 * * * /home/accomplishments/app/deploy/backup.sh >> /home/accomplishments/backup.log 2>&1
```

Backups land in `/home/accomplishments/backups/` and the script prunes anything older than 14 days. For real safety, periodically copy them off the droplet — `scp` from your local machine works, or look into `restic` with a B2/R2 backend.

## Updating the app later

```bash
cd /home/accomplishments/app
sudo -u accomplishments git pull
sudo -u accomplishments .venv/bin/pip install -r requirements.txt
sudo systemctl restart accomplishments
```

## Troubleshooting

- **App won't start:** `sudo journalctl -u accomplishments -n 50`
- **Caddy issues:** `sudo journalctl -u caddy -n 50`
- **Permission errors on uploads:** make sure `/home/accomplishments/app/uploads` is owned by `accomplishments:accomplishments`
- **Database locked errors:** SQLite handles concurrency fine for one user; if you see this, something's holding a transaction open

## Suggested next steps

Once you have it running, consider these as small projects to deepen your learning:

1. **Authentication** — even for solo use, add a login page (Flask-Login is straightforward) so the app isn't open to the internet
2. **Full-text search** — SQLite's FTS5 extension lets you search descriptions
3. **Tags** — a many-to-many tags table for finer-grained labeling
4. **Object storage** — once you have a real reason for it, migrate uploads to Cloudflare R2 or Backblaze B2
5. **CI/CD** — a GitHub Action that SSHes into the droplet and runs the update commands on every push to main
