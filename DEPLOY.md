# Production deployment on a Linux VPS

This setup runs Flask with Gunicorn behind Nginx and keeps SQLite, uploaded files, and article images in `Tether/runtime`.

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

5. If an existing local database or `users.json` should be used, copy them into `Tether/runtime/`.
6. Start the stack:

   ```sh
   docker compose up -d --build
   docker compose ps
   curl http://127.0.0.1/healthz
   ```

The site is available on port 80. Put a TLS terminator such as Certbot/Nginx or a cloud load balancer in front of it before exposing it publicly.

## Updating

```sh
git pull
docker compose up -d --build
docker image prune -f
```

## Backups

Back up `Tether/runtime/` regularly. It contains the SQLite database, user configuration, uploaded files, and article images. Do not commit `.env`, OAuth client secrets, or the runtime directory.

## Useful commands

```sh
docker compose logs -f web
docker compose logs -f nginx
docker compose restart web
```
