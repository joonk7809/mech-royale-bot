FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=main_v1ag
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":100,"finish_low":true}'
ENV MECH_IDLE_T=120
ENV MECH_MAIN_CFG='{"grounded":true,"pinned_check":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
