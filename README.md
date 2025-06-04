<h2>The idea</h2>
The 'archeo_db' project is a database layer modeling for a field database of facts of destructive 
archaeological research (excavation research). It is conceptually based on a general analysis of 
research and definition of research entities:

here ENG - https://archeoconsult.org/good-data/good-data-internal/excavation-docu-standard/

here SK - https://archeoconsult.org/good-data/good-data-internal/standard-terenneho-vyskumu-a-jeho-dokumentacie-sk/

It is not a specialized database, but of general use (universal archaeological terain excavation) and created in 
PostgreSQL environment - hence relation standard.

Webapp stack is written in python/Flask environment

<h2>How to install</h2>

python 3
requirements.txt

<h3>For DEV/TEST</h3>

1. git clone / git pull
2. customize config.py for DB credentials, log/file paths

<h3>PROD environment philosophy:</h3>

1. Flask ---> Gunicorn
2. Gunicorn configured as systemd daemon/service
3. Nginx like a reverse proxy
4. pip install -r requirements.txt
5. virtual environment is ready (python3 -m venv venv)
6. runs locally (flask run or python run.py)
7. config.py is modified for your needs

<h3>how to prepare Gunicorn as a systemd daemon</h3>

<code>vim /etc/systemd/system/archeodb.service</code>

###
#customize Your paths
###

[Unit]
Description=Gunicorn instance to serve archeodb
After=network.target

[Service]
User=your_user
Group=www-data
WorkingDirectory=/home/your_user/web_app
Environment="PATH=/home/your_user/web_app/venv/bin"
ExecStart=/home/your_user/web_app/venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 run:app

[Install]
WantedBy=multi-user.target



<code>sudo systemctl enable archeodb</code>
<code>sudo systemctl start archeodb</code>
