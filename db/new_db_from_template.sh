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
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -c "CREATE DATABASE $DB_NAME TEMPLATE $DB_TEMPLATE;"

# result - OK, or not
if [ $? -eq 0 ]; then
    echo "Database $DB_NAME was sucessfully created."
else
    echo "Error while creating DB $DB_NAME."
    exit 1
fi
