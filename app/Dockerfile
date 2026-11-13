# Official Node image from the AWS public registry mirror, pinned by digest (never a moving tag).
FROM public.ecr.aws/docker/library/node:22.23.4-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202

WORKDIR /app
# No install step and no dependencies: only our own files go into the image.
COPY package.json ./
COPY src ./src
RUN mkdir /data && chown node:node /data

ENV NODE_ENV=production \
    SMPLDOC_DATA_DIR=/data \
    SMPLDOC_HOST=0.0.0.0 \
    SMPLDOC_PORT=3787

USER node
EXPOSE 3787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3787/health').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]
CMD ["node", "src/adapters/serve.ts"]
