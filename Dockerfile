FROM python:3.13-slim
RUN pip install --no-cache-dir numpy==2.3.5
WORKDIR /bot
COPY bots /bot/bots
COPY geo /bot/geo
RUN python3 -m compileall -q /bot
ENV PYTHONDONTWRITEBYTECODE=1
ENV MECH_MAIN_CFG='{"grounded":true,"pinned_check":true}'
ENTRYPOINT ["python3", "-u", "/bot/bots/run_stdio.py", "main"]
