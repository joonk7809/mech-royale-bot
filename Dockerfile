FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=main_v1ag
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":100,"grounded":true,"climb_out":false,"mortar_use":false,"weapon_pref":{"laser":3.0,"lightning":2.0,"gun":1.5,"mortar":0.0},"upgrade_rank":["plating","armor","gun_rate","gun_damage","nanites","laser_damage","laser_charge","sensors","servos","gyros","gun_mag","lightning_efficiency","lightning_range","lightning_chain","capacitor","reactor","jets","gun_velocity","laser_pierce","mortar_reload","mortar_velocity","mortar_splash"]}'
ENV MECH_MAIN_CFG='{"grounded":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
