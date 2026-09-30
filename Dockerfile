# trendwatch — GitHub trending + topics as a markdown digest
#
# Build:  docker build -t wallydk24/trendwatch .
# Run:    docker run --rm wallydk24/trendwatch digest --help
# Stdlib only. `gh` enrichment is best-effort and skipped automatically
# when the gh CLI isn't present (use --no-enrich to skip it explicitly).

FROM python:3.12-alpine

WORKDIR /app
COPY trendwatch.py ./
RUN adduser -D tw && chown -R tw:tw /app
USER tw

ENTRYPOINT ["python3", "/app/trendwatch.py"]
CMD ["--help"]
