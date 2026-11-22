FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=moon
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":200,"finish_low":true,"medkit":true,"weapon_pref":{"laser":5.0,"gun":1.5,"lightning":0.5,"mortar":0.0},"mortar_use":false,"fight_range_scale":1.6,"upgrade_rank":["laser_charge","laser_damage","plating","armor","nanites","sensors","gun_rate","gun_damage","servos","gyros","gun_mag","gun_velocity","laser_pierce","lightning_efficiency","lightning_range","lightning_chain","capacitor","reactor","jets","mortar_reload","mortar_velocity","mortar_splash"]}'
ENV MECH_MAIN_CFG='{"grounded":true,"pinned_check":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
