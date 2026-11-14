# syntax=docker/dockerfile:1
FROM alpine:3.20 AS build
ARG GREETING=hello
RUN --mount=type=cache,target=/var/cache/apk apk add --no-cache curl >/dev/null && echo "$GREETING from build" > /out.txt
RUN --mount=type=secret,id=tok sh -c 'test -s /run/secrets/tok && echo secret-ok >> /out.txt'
COPY app.txt /app.txt
FROM alpine:3.20
COPY --from=build /out.txt /app.txt /srv/
CMD ["cat", "/srv/out.txt", "/srv/app.txt"]
