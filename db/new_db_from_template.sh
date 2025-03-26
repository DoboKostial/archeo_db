#!/bin/bash

#this script use tempalte and create brand new database from template
#use parameter as name of new DB

DB_NAME=$1
DB_TEMPLATE="terrain_db_template"

# conninfo
PGUSER="postgres"     # Uživatelské jméno
PGHOST="localhost"    # Hostitel
PGPORT="5432"         # Port (výchozí je 5432)
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
