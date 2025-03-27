#!/bin/bash

#this script use tempalte and create brand new database from template
#use parameter1 as name of new DB and parameter2 as DB owner (app role)

DB_NAME=$1
DB_OWNER=$2
DB_TEMPLATE="terrain_db_template"

# conninfo
PGUSER="postgres"     # superuser
PGHOST="localhost"    # host
PGPORT="5432"         # port
#using .pgpass

# new DB from template

if psql -U $PGUSER -h $PGHOST -p $PGPORT -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
  echo "Database $DB_NAME already exists!"
else
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "CREATE DATABASE $DB_NAME TEMPLATE $DB_TEMPLATE;"
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "ALTER DATABASE $DB_NAME OWNER TO $DB_OWNER;"
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_OWNER;"
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "GRANT CONNECT ON DATABASE terrain_db_template TO grp_dbas;"
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "GRANT CONNECT ON DATABASE terrain_db_template TO grp_analysts;"
fi

# result - OK, or not
if [ $? -eq 0 ]; then
    echo "Database $DB_NAME was sucessfully created and reowned."
else
    echo "Error while creating DB $DB_NAME."
    exit 1
fi
