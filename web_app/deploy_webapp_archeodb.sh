#!/bin/bash

# ==== VARS (customize!) ====
USER="dobo"
APP_DIR="/var/www/archeodb_web_app"
VENV="$APP_DIR/venv"
SERVICE="/etc/systemd/system/archeodb.service"
NGINX_CONF="/etc/nginx/sites-available/archeodb"
DOMAIN="FQDN of Your server"

cd $APP_DIR

# ==== 1. Create venv, if not exists ====
if [ ! -d "$VENV" ]; then
    python3 -m venv venv
    echo "New venv created."
else
    echo "venv already exists, skipping."
fi

# ==== 2. Activate venv and install requirements ====
source $VENV/bin/activate
if [ -f requirements.txt ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "Requirements installed."
else
    echo "ERROR: requirements.txt not found!"
fi
deactivate

# ==== 3. Gunicorn systemd service ====
cat <<EOF | sudo tee $SERVICE
[Unit]
Description=Gunicorn instance to serve archeodb
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV/bin"
ExecStart=$VENV/bin/gunicorn -w 4 -b 127.0.0.1:8000 run:app
Restart=on-failure
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable archeodb
sudo systemctl restart archeodb

# ==== 4. Nginx config ====
cat <<EOF | sudo tee $NGINX_CONF
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    access_log /var/log/nginx/archeodb_access.log;
    error_log /var/log/nginx/archeodb_error.log;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    client_max_body_size 25M;
}
EOF

sudo ln -sf $NGINX_CONF /etc/nginx/sites-enabled/archeodb
sudo nginx -t && sudo systemctl reload nginx

echo "=================================="
echo "Deploy finished! Check:"
echo "- Gunicorn status: sudo systemctl status archeodb"
echo "- Nginx status:    sudo systemctl status nginx"
echo "- Web:           https://$DOMAIN/"
echo "=================================="

