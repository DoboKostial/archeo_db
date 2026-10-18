<h2>The idea</h2>
The 'archeo_db' project is a database layer modeling for a field database of facts of destructive 
archaeological research (excavation research). It is conceptually based on a general analysis of 
research and definition of research entities:

here ENG - https://archeoconsult.org/good-data/good-data-internal/excavation-docu-standard/

here SK - https://archeoconsult.org/good-data/good-data-internal/standard-terenneho-vyskumu-a-jeho-dokumentacie-sk/

It is not a specialized database, but of general use (universal archaeological terain excavation) and created in 
PostgreSQL environment - hence relation standard.

<h2>Features</h2>
* Online database cluster of primary field facts from archaeological research, web access or mobile application
* Comprehensive user administration (RBAC), database management (possibility to choose from multiple projects/databases), backup
* 
* Integrated map projection system and map portal, GIS/CAD integration (access to DB using your GIS/CAD environment)
* Recording of research polygons, stratigraphic units, Harris matrix, sections, geodesy; complete management of image data (photos, photograms, sketches, drawings)
* Analytical module checking data consistency
* Reporting module enabling export of facts to PDF, SQL, MS Excel
* 
* BSD 3-Clause License



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

... or just simply use deploy script deploy_webapp_archeodb.sh

