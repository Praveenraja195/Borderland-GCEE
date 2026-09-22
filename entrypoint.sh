#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
python -c "
import socket, time, os, sys
from urllib.parse import urlparse

url = os.getenv('DATABASE_URL', '')
if url:
    url_clean = url.replace('postgresql+asyncpg://', 'http://').replace('postgresql+psycopg2://', 'http://').replace('postgresql://', 'http://')
    parsed = urlparse(url_clean)
    host = parsed.hostname or 'postgres'
    port = parsed.port or 5432
    for i in range(30):
        try:
            with socket.create_connection((host, port), timeout=2):
                print('PostgreSQL is accepting connections.')
                sys.exit(0)
        except Exception:
            time.sleep(1)
    print('PostgreSQL connection wait timed out.')
"

if [ "$RUN_MIGRATIONS" = "true" ]; then
    # In production a failed migration must stop the container (the health
    # check then keeps Caddy/worker from starting on a broken schema); in
    # development it is only reported so a partially-migrated DB stays usable.
    echo "Running Alembic migrations..."
    if ! alembic upgrade head; then
        if [ "$ENVIRONMENT" = "production" ]; then
            echo "FATAL: database migration failed; refusing to start." >&2
            exit 1
        fi
        echo "Alembic migration step finished with warnings/errors."
    fi

    echo "Seeding default admin user..."
    if ! python -m app.db.seed_admin; then
        if [ "$ENVIRONMENT" = "production" ]; then
            echo "FATAL: admin seed failed; refusing to start." >&2
            exit 1
        fi
        echo "Admin seed step finished with warnings/errors."
    fi
fi

exec "$@"
