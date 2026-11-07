# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/sanduniwwijesinghe/geo-flood-monitor" \
      org.opencontainers.image.description="Sentinel-2 flood-extent pipeline for Sri Lanka"
# rasterio wheels bundle GDAL, so no system GDAL is needed - only libexpat,
# which newer slim base images no longer ship. `upgrade` pulls in Debian security
# fixes released after the base image was built (keeps the Trivy gate green).
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /install /usr/local
RUN useradd --uid 10001 --create-home geoflood && mkdir /output && chown geoflood /output
USER 10001
ENV GEOFLOOD_OUTPUT_DIR=/output \
    PYTHONUNBUFFERED=1 \
    GDAL_HTTP_MAX_RETRY=3 \
    GDAL_HTTP_RETRY_DELAY=2 \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif
ENTRYPOINT ["geoflood"]
CMD ["list-aois"]
