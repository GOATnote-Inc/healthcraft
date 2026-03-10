FROM postgres:16

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql

ENV POSTGRES_DB=healthcraft
ENV POSTGRES_USER=healthcraft
