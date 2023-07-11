FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends \
  dumb-init \
  && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /app

RUN groupadd -r etl_grp && useradd -d /home/etl_user -m -r -g etl_grp etl_user
RUN chown -R etl_user:etl_grp /app
USER etl_user

COPY --chown=etl_user:etl_grp requirements.txt requirements.txt
RUN pip3 install --user -r requirements.txt
COPY src/ /app
ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/entrypoint.sh"]

