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
    echo "Running Alembic migrations..."
    alembic upgrade head || echo "Alembic migration step finished with warnings/errors."

    echo "Seeding default admin user..."
    python -m app.db.seed_admin || echo "Admin seed step finished with warnings/errors."
fi

exec "$@"
