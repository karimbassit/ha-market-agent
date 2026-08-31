FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="1.0.0"
ARG BUILD_ARCH="aarch64"
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.name="Market Agent" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 ca-certificates tzdata

WORKDIR /opt/market-agent
COPY . /opt/market-agent
RUN chmod 0755 /opt/market-agent/run-addon.sh

ENTRYPOINT ["/opt/market-agent/run-addon.sh"]
