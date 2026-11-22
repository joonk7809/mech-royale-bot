# giddygiddyboy

A bot for the Builders Buildathon Mech Royale track (protocol `mechfight/1`). Go, standard library only.

```sh
docker build --platform linux/amd64 -t bot .
```

## Our changes (team joonk7809, on top of giddygiddyboy's MIT bot)

- `mech/override.go`: `MECH_P` / `MECH_SQUAD_P` environment overrides (`Key=value,...`) for any `Params` field, applied to the base params and to the practice-squad params; unset means identical behaviour.
- `PracT` param: time after which the bot assumes the practice squad (was a fixed 20 s).
- `HealLo` / `HealHi` params (off by default): hit-and-heal. Once HP falls below `HealLo` while losing or out of contact, keep retreating until HP regenerates to `HealHi` (the squad LoseRule otherwise retreats for only 1.5 s).
- `LateHide` param (off by default): after this time, take cover whenever exposed unless finishing a target.
- `NPUntil` param (off by default): only leave practice-squad mode on unexplained deaths before this time. Late zone or drone deaths of house bots otherwise switch the bot back to FFA params mid-practice.
- `OpenAvoid` param (off by default): before this time, when 2+ enemies are seen within 120 m, take cover or move away instead of fighting (unless finishing). `AvoidN` / `AvoidR` set the count and radius.
- `SquadUntil` param (off by default): use the practice-squad params only until this time, then the base (stealthier) params.
- `HealAfter` param (default 0): hit-and-heal only applies after this time.
- `HoldFire` param (default 0): never fire before this time (probe for whether house bystanders only attack once provoked).
- `FrontKeep` param (default 0): target-score penalty per other visible enemy within 150 m that would be outside our front arc (rear hits deal x1.5) while aiming at that target.
- Variant branches `giddy/<name>` set these through `ENV` lines in the `Dockerfile`.
