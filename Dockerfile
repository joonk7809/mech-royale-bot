FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=main_v1ag
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":100,"finish_low":true,"harvest":true,"harvest_cap":28,"press_min_hp":0,"finish_frac":1.0,"finish_min_hp":0,"retreat_hp":0,"regen_hide":false,"weapon_pref":{"laser":3.0,"lightning":2.0,"gun":1.5,"mortar":0.0},"mortar_use":false}'
ENV MECH_MAIN_CFG='{"grounded":true,"pinned_check":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
