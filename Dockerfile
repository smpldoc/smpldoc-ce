# smpldoc-ce image. The base is pinned by digest; Dependabot proposes updates. No build tools, no
# package installs: the app is the standard library plus the files in smpldoc/.
FROM python:3.12-slim-trixie@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

# Smaller attack surface: nothing here needs pip at run time.
RUN python -m pip uninstall -y pip setuptools wheel >/dev/null 2>&1 || true \
 && groupadd --system --gid 10001 smpldoc \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin smpldoc \
 && mkdir /data && chown 10001:10001 /data && chmod 700 /data

WORKDIR /app
COPY smpldoc/ /app/smpldoc/

# Inside a container the app must listen on all interfaces so the host can reach it. That is safe
# because only health checks are served, and the app refuses to start on a public bind if any
# route needs sign-in that is not configured. Publish the port on 127.0.0.1 unless you mean otherwise.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    SMPLDOC_DATA_DIR=/data SMPLDOC_BIND=0.0.0.0 SMPLDOC_PORT=8080

USER 10001:10001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:'+os.environ.get('SMPLDOC_PORT','8080')+'/healthz', timeout=3).status==200 else 1)"]
ENTRYPOINT ["python", "-m", "smpldoc"]
CMD ["run"]
