"""Output sinks: Azure Blob Storage for COGs, PostGIS for event metadata."""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS flood_events (
    id                 BIGSERIAL PRIMARY KEY,
    aoi                TEXT        NOT NULL,
    event_scene_id     TEXT        NOT NULL,
    event_datetime     TIMESTAMPTZ NOT NULL,
    baseline_scene_id  TEXT        NOT NULL,
    flooded_km2        DOUBLE PRECISION NOT NULL,
    permanent_water_km2 DOUBLE PRECISION NOT NULL,
    valid_fraction     DOUBLE PRECISION NOT NULL,
    cog_url            TEXT        NOT NULL,
    footprint          GEOMETRY(Polygon, 4326) NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (aoi, event_scene_id)
);
CREATE INDEX IF NOT EXISTS flood_events_footprint_gix ON flood_events USING GIST (footprint);
"""


def upload_blob(local_path: str, blob_name: str) -> str:
    """Upload to Azure Blob. Uses Workload Identity on AKS, or a connection string locally.

    Returns the blob URL, or the local path if no storage is configured.
    """
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    container = os.getenv("AZURE_STORAGE_CONTAINER", "flood-cogs")
    if not (account_url or conn_str):
        log.info("No Azure storage configured; keeping output at %s", local_path)
        return local_path

    from azure.storage.blob import BlobServiceClient, ContentSettings

    if conn_str:
        service = BlobServiceClient.from_connection_string(conn_str)
    else:
        from azure.identity import DefaultAzureCredential

        service = BlobServiceClient(account_url, credential=DefaultAzureCredential())

    blob = service.get_blob_client(container=container, blob=blob_name)
    with open(local_path, "rb") as fh:
        blob.upload_blob(
            fh, overwrite=True, content_settings=ContentSettings(content_type="image/tiff")
        )
    log.info("Uploaded %s", blob.url)
    return blob.url


def record_event(row: dict, footprint: dict) -> None:
    """Upsert one flood analysis result into PostGIS (skipped if DATABASE_URL unset)."""
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        log.info("DATABASE_URL not set; skipping PostGIS write")
        return

    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
        cur.execute(
            """
            INSERT INTO flood_events (aoi, event_scene_id, event_datetime, baseline_scene_id,
                flooded_km2, permanent_water_km2, valid_fraction, cog_url, footprint)
            VALUES (%(aoi)s, %(event_scene_id)s, %(event_datetime)s, %(baseline_scene_id)s,
                %(flooded_km2)s, %(permanent_water_km2)s, %(valid_fraction)s, %(cog_url)s,
                ST_SetSRID(ST_GeomFromGeoJSON(%(footprint)s), 4326))
            ON CONFLICT (aoi, event_scene_id) DO UPDATE SET
                flooded_km2 = EXCLUDED.flooded_km2,
                permanent_water_km2 = EXCLUDED.permanent_water_km2,
                valid_fraction = EXCLUDED.valid_fraction,
                cog_url = EXCLUDED.cog_url,
                created_at = now()
            """,
            {**row, "footprint": json.dumps(footprint)},
        )
    log.info("Recorded flood event for %s in PostGIS", row["aoi"])
