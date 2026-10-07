#!/bin/sh
# Apply the schema, then serve.
#
# The app never migrates at import time, so without this a fresh volume answers
# every request with "relation does not exist". One container owns the schema,
# so there is no race between replicas — add a lock before scaling this out.
#
# gthread + a long timeout is for the sync endpoints: they call Codeforces
# synchronously, paced at 2 s per call, and user.status pages up to 20 times, so
# one request can legitimately run for minutes. Threads keep the rest of the app
# answering while that happens; the default 30 s worker timeout would kill it.
set -e

flask --app app db upgrade

exec gunicorn \
    --bind 0.0.0.0:5001 \
    --worker-class gthread \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    "app:create_app()"
