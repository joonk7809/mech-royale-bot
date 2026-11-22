# giddygiddyboy

A bot for the Builders Buildathon Mech Royale track (protocol `mechfight/1`). Go, standard library only.

```sh
docker build --platform linux/amd64 -t bot .
```

## Our changes (team joonk7809, on top of giddygiddyboy's MIT bot)

- `mech/override.go`: `MECH_P` / `MECH_SQUAD_P` environment overrides (`Key=value,...`) for any `Params` field, applied to the base params and to the practice-squad params; unset means identical behaviour.
- `PracT` param: time after which the bot assumes the practice squad (was a fixed 20 s).
- `HealLo` / `HealHi` params (off by default): hit-and-heal. Once HP falls below `HealLo` while losing or out of contact, keep retreating until HP regenerates to `HealHi` (the squad LoseRule otherwise retreats for only 1.5 s).
- Variant branches `giddy/<name>` set these through `ENV` lines in the `Dockerfile`.
