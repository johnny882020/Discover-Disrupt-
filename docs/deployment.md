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
3. **Verify it.** Replace `<service>` with your service's name:

   ```bash
   curl https://<service>.onrender.com/health
   # {"status":"ok"}

   curl -X POST https://<service>.onrender.com/pipelines/run \
     -H 'content-type: application/json' \
     -d '{"source": "csv", "path": "/app/samples/lab_export_malformed.csv"}'
   ```

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

## Docker Compose

```bash
docker compose up --build
```

This starts the API on <http://localhost:8000> with a local PostgreSQL.
