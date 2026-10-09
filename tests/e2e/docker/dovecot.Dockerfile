FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends dovecot-imapd && rm -rf /var/lib/apt/lists/*
CMD ["dovecot","-F"]
