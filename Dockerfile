# Liefert die fertige Website aus dist/ aus (gebaut lokal mit build_site.py, KiCad noetig)
FROM caddy:2.8.4-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY dist /srv
