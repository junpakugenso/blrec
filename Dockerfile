# syntax=docker/dockerfile:1
# Multi-platform index: linux/amd64 and linux/arm64; update only in a tested release.
FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 AS builder
WORKDIR /build
COPY docker/constraints.txt /build/constraints.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pip==25.0.1 setuptools==70.3.0 wheel==0.45.1
COPY src/ src/
COPY setup.py setup.cfg MANIFEST.in README.md LICENSE ./
# Deliberately use the Docker toolchain, not the original pyproject build pins.
RUN python -m pip wheel --no-cache-dir --no-build-isolation \
    -c constraints.txt -w /wheels . setuptools==70.3.0

FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84
ARG VERSION
ARG REVISION
LABEL org.opencontainers.image.source="https://github.com/junpakugenso/blrec" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="GPL-3.0-only"
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY LICENSE README.md /app/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --no-index --find-links=/wheels "blrec==${VERSION}" setuptools==70.3.0 \
    && python -m pip check \
    && python -c "import blrec, importlib.metadata as m; assert blrec.__version__ == m.version('blrec') == '${VERSION}'" \
    && rm -rf /wheels
ENV BLREC_DEFAULT_SETTINGS_FILE=/cfg/settings.toml \
    BLREC_DEFAULT_LOG_DIR=/log \
    BLREC_DEFAULT_OUT_DIR=/rec \
    TZ=Asia/Shanghai
VOLUME ["/cfg", "/log", "/rec"]
EXPOSE 2233
ENTRYPOINT ["blrec", "--host", "0.0.0.0", "--no-progress"]
CMD []
