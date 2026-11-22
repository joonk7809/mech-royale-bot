FROM golang:1.26.1-bookworm@sha256:ab3d6955bbc813a0f3fdf220c1d817dd89c0b3f283777db8ece4a32fe7858edd AS build
WORKDIR /src
COPY go.mod ./
COPY mech ./mech
COPY cmd/bot ./cmd/bot
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /mechbot ./cmd/bot

FROM scratch
COPY --from=build /mechbot /mechbot
ENTRYPOINT ["/mechbot"]
ENV MECH_P=NPUntil=60,OpenAvoid=12,AvoidN=1,AvoidR=170
ENV MECH_SQUAD_P=LateHide=300,Ghost=true,Peek=true,HealLo=0.6,HealHi=0.95,HealAfter=300
