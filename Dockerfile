FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_DUAL_SEED=urandom
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "dual"]
