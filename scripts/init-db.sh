#!/bin/sh
set -eu
# psql variables are SQL-quoted; passwords never become shell code or log output.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=app_password="$POSTGRES_APP_PASSWORD" --set=n8n_password="$POSTGRES_N8N_PASSWORD" <<'SQL'
CREATE USER videott WITH PASSWORD :'app_password';
CREATE DATABASE videott OWNER videott;
CREATE USER n8n WITH PASSWORD :'n8n_password';
CREATE DATABASE n8n OWNER n8n;
REVOKE CONNECT ON DATABASE videott FROM PUBLIC;
REVOKE CONNECT ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT ON DATABASE videott TO videott;
GRANT CONNECT ON DATABASE n8n TO n8n;
SQL
