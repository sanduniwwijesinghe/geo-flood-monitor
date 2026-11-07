"""Batch-job metrics pushed to a Prometheus Pushgateway (jobs are too short-lived to scrape)."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

log = logging.getLogger(__name__)


class PipelineMetrics:
    def __init__(self, aoi: str):
        self.aoi = aoi
        self.registry = CollectorRegistry()
        self.duration = Gauge(
            "geoflood_pipeline_duration_seconds",
            "Wall time of the last run",
            registry=self.registry,
        )
        self.last_success = Gauge(
            "geoflood_last_success_timestamp_seconds",
            "Unix time of the last successful run",
            registry=self.registry,
        )
        self.last_failure = Gauge(
            "geoflood_last_failure_timestamp_seconds",
            "Unix time of the last failed run",
            registry=self.registry,
        )
        self.flooded = Gauge(
            "geoflood_flooded_area_km2",
            "Newly flooded area in last analysis",
            registry=self.registry,
        )
        self.valid = Gauge(
            "geoflood_valid_pixel_ratio", "Cloud-free fraction of the AOI", registry=self.registry
        )
        self.scene_age = Gauge(
            "geoflood_event_scene_age_seconds",
            "Age of the newest satellite scene analysed",
            registry=self.registry,
        )

    @contextmanager
    def run(self):
        start = time.time()
        try:
            yield self
            self.last_success.set_to_current_time()
        except Exception:
            self.last_failure.set_to_current_time()
            raise
        finally:
            self.duration.set(time.time() - start)
            self.push()

    def push(self) -> None:
        gateway = os.getenv("PUSHGATEWAY_URL")
        if not gateway:
            return
        try:
            push_to_gateway(
                gateway, job="geoflood", registry=self.registry, grouping_key={"aoi": self.aoi}
            )
        except Exception as exc:  # metrics must never fail the pipeline
            log.warning("Pushgateway push failed: %s", exc)
