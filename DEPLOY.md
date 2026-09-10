# Production deployment on a Linux VPS

This setup runs Flask with Gunicorn behind Nginx and PostgreSQL for application data. Uploaded files and article images remain in `Tether/runtime`.

## First deployment

1. Install Docker Engine and Docker Compose plugin on the VPS.
2. Copy this repository to the VPS.
3. Create the runtime directories:

   ```sh
   mkdir -p Tether/runtime/uploads Tether/runtime/Pics
   ```

4. Create the environment file and replace all placeholder values:

   ```sh
   cp .env.example .env
   chmod 600 .env
   ```

5. If an existing `users.json` should be used, copy it into `Tether/runtime/`. The PostgreSQL database is stored in the named Docker volume `postgres_data`.
6. Start the stack:

   ```sh
   docker compose up -d db
   docker compose run --rm web python /app/migrate_sqlite_to_postgres.py
   docker compose up -d --build
   docker compose ps
   curl http://127.0.0.1/healthz
   ```

The site is available on port 80. Put a TLS terminator such as Certbot/Nginx or a cloud load balancer in front of it before exposing it publicly.

## Importing the existing SQLite database

The SQLite file cannot be mounted as a PostgreSQL database. Import it once into the new PostgreSQL service:

```sh
docker compose up -d db
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1"'
```

Run the migration through the Compose network. The database is not exposed publicly:

```sh
docker compose run --rm web python /app/migrate_sqlite_to_postgres.py
```

After the import, start the complete stack with `docker compose up -d --build`.

## Updating

```sh
git pull
docker compose up -d --build
docker image prune -f
```

## Backups

Back up the PostgreSQL volume and `Tether/runtime/` regularly. The runtime directory contains user configuration, uploaded files, and article images. Do not commit `.env`, OAuth client secrets, or the runtime directory.

Create a PostgreSQL dump with:

```sh
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > tether-$(date +%F).sql
```

## Useful commands

```sh
docker compose logs -f web
docker compose logs -f db
docker compose logs -f nginx
docker compose restart web
```
