# Deployment

## Render

The repository includes a [Render Blueprint](https://render.com/docs/blueprint-spec)
(`render.yaml`) that provisions two resources:

| Resource | Type | Notes |
|---|---|---|
| `dndlabs-api` | Web service (Docker) | Built from `docker/Dockerfile`; health check `/health` |
| `dndlabs-db` | PostgreSQL | Its connection string is passed to the API as `DNDLABS_DATABASE_URL` |

On every deploy the container applies database migrations
(`dnd-pipeline init-db`) and then starts the API on the port Render assigns
(`$PORT`).

### Deploy

1. **Open the Blueprint.** Either click the button (it reads `render.yaml`
   from the repository's default branch):

   [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/johnny882020/Discover-Disrupt-)

   Or, in the Render Dashboard, choose **New → Blueprint**, connect this
   repository, and select the branch to deploy.
2. **Apply it.** Review the two resources and click **Apply**. The first
   build takes a few minutes, mostly installing RDKit.
3. **Verify it.** Replace `<service>` with your service's name, then run the
   end-to-end smoke test from a local checkout:

   ```bash
   python scripts/smoke_test.py https://<service>.onrender.com --pubchem
   ```

   ```text
   Smoke test: https://<service>.onrender.com
     ok  root: D&D Labs Data API 0.1.0
     ok  health
     ok  /docs
     ok  csv lab export: 5/12 accepted, pass rate 41.7%
     ok  json upload: 2/4 accepted, pass rate 50.0%
     ok  pubchem cids: 3/3 accepted, pass rate 100.0%
   All smoke checks passed.
   ```

   Or run it from GitHub without a local checkout: **Actions → Smoke test →
   Run workflow**, then enter the service URL.

   Or check it by hand:

   ```bash
   curl https://<service>.onrender.com/          # service info and endpoint list
   curl https://<service>.onrender.com/health    # {"status":"ok"}
   ```

   Swagger UI is at `https://<service>.onrender.com/docs`.

The sample files in `tests/fixtures/` are built into the image at
`/app/samples/`.

### Configuration

The Blueprint sets:

| Variable | Value |
|---|---|
| `DNDLABS_DATABASE_URL` | From `dndlabs-db`. A bare `postgres://` or `postgresql://` URL is rewritten to use the psycopg 3 driver. |
| `DNDLABS_AUTO_CREATE_SCHEMA` | `false`, because Alembic manages the schema |
| `DNDLABS_EXPORT_DIR` | `/app/exports` |
| `DNDLABS_LOG_LEVEL` | `INFO` |

You can set any other `DNDLABS_*` variable under the service's
**Environment** tab. See the configuration table in the
[README](../README.md#configuration).

### Plans and limits

`render.yaml` uses the **free** plans, which suit a demo:

| Limit | Effect |
|---|---|
| Free web services sleep when idle | The first request after a sleep takes about a minute. |
| Free PostgreSQL databases expire after 30 days | Data is lost when the database expires. |
| The service disk is not persistent | Files in `DNDLABS_EXPORT_DIR` are lost on redeploy. Datasets stay in Postgres and can always be downloaded again from `GET /datasets/{id}/export`. |

For production, change `plan:` in `render.yaml` to a paid plan, for example
`starter` for the web service and `basic-256mb` for the database.

### Notes

- **No authentication.** The API is public once deployed. Don't load
  confidential data until authentication has been added.
- **Deploy branch.** `autoDeploy: true` redeploys on every push to the
  branch the Blueprint tracks.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `{"detail":"Not Found"}` | The URL has no route; the service itself is running. Open `/` for the list of endpoints, or `/docs`. Versions before the root endpoint was added also returned this at `/`. |
| First request takes about a minute | The free plan puts the service to sleep when idle; the first request wakes it. |
| Run `failed` with `CSV file not found` | `path` is read on the server. Use `/app/samples/...` or another path inside the container. |
| Run `failed` with `PubChem unreachable` | PubChem is down or rate-limiting the service. The error is stored on the run; retry later. |
| Deploy fails during `init-db` | The database is unreachable or expired (free Postgres lasts 30 days). Check `dndlabs-db` in the Render Dashboard. |

To redeploy, push to `main` (`autoDeploy: true`), or use **Manual Deploy →
Deploy latest commit** on the service page.

## Docker Compose

```bash
docker compose up --build
```

This starts the API on <http://localhost:8000> with a local PostgreSQL.
