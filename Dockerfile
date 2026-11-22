FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=main_v1ag
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":100,"finish_low":true,"upgrade_rank":["nanites","plating","armor","gun_rate","gun_damage","laser_damage","laser_charge","sensors","servos","gyros","gun_mag","lightning_efficiency","lightning_range","lightning_chain","capacitor","reactor","jets","gun_velocity","laser_pierce","mortar_reload","mortar_velocity","mortar_splash"]}'
ENV MECH_MAIN_CFG='{"grounded":true,"pinned_check":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
