FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENV MECH_DUAL_SQUAD=main_v1ag
ENV MECH_DUAL_OPEN=v1
ENV MECH_DUAL_V1='{"squad_press":true,"press_r":100,"squad_avoid":true}'
ENV MECH_MAIN_CFG='{"grounded":true,"grounded_ffa_only":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
