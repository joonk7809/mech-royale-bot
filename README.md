# giddygiddyboy

A bot for the Builders Buildathon Mech Royale track (protocol `mechfight/1`). Go, standard library only.

```sh
docker build --platform linux/amd64 -t bot .
```

## Our changes (team joonk7809, on top of giddygiddyboy's MIT bot)

- `mech/override.go`: `MECH_P` / `MECH_SQUAD_P` environment overrides (`Key=value,...`) for any `Params` field, applied to the base params and to the practice-squad params; unset means identical behaviour.
- `PracT` param: time after which the bot assumes the practice squad (was a fixed 20 s).
- Variant branches `giddy/<name>` set these through `ENV` lines in the `Dockerfile`.
