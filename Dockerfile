# trendwatch — GitHub trending + topics as a markdown digest
# (multi-arch: linux/amd64, linux/arm64 — e.g. Raspberry Pi)
#
# Build:  podman build --platform linux/arm64 -t wallydk24/trendwatch:arm64 .
# Run:    docker run --rm wallydk24/trendwatch digest --no-enrich
# Stdlib only. `gh` enrichment is best-effort and skipped automatically
# when the gh CLI isn't present (use --no-enrich to skip it explicitly).

FROM python:3.12-alpine

WORKDIR /app
COPY trendwatch.py ./
USER 1000

ENTRYPOINT ["python3", "/app/trendwatch.py"]
CMD ["--help"]
