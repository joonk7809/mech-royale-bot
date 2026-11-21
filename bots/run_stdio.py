import importlib
import json
import os
import queue
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONTINUOUS = ("move", "aim", "boost")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def send(out, msg):
    out.write(json.dumps(msg, separators=(",", ":")) + "\n")
    out.flush()


def reader(q):
    for line in sys.stdin:
        if line.strip():
            q.put(line)
    q.put(None)


def main(name):
    out = sys.stdout
    mod = importlib.import_module(f"bots.{name}.bot")
    q = queue.Queue()
    threading.Thread(target=reader, args=(q,), daemon=True).start()
    bot = None
    last = {}
    errors = 0
    slow = 0
    while True:
        batch = [q.get()]
        while True:
            try:
                batch.append(q.get_nowait())
            except queue.Empty:
                break
        latest = None
        for raw in batch:
            if raw is None:
                return
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "hello":
                t0 = time.perf_counter()
                try:
                    bot = mod.Bot(msg)
                except Exception:
                    log(traceback.format_exc())
                    bot = None
                log(f"{name}: hello {1000 * (time.perf_counter() - t0):.0f} ms nav={getattr(bot, 'navkind', None)}")
                send(out, {"type": "ready", "name": str(getattr(mod, "NAME", name))[:32]})
            elif kind == "obs":
                latest = msg
            elif kind == "end":
                if bot is not None:
                    try:
                        bot.end(msg)
                    except Exception:
                        log(traceback.format_exc())
                return
        if latest is None:
            continue
        action = {}
        if bot is not None:
            t0 = time.perf_counter()
            try:
                action = dict(bot.act(latest) or {})
                last = {k: action[k] for k in CONTINUOUS if k in action}
            except Exception:
                errors += 1
                if errors <= 5 or errors % 100 == 0:
                    log(f"act failed at tick {latest.get('tick')} ({errors}):\n{traceback.format_exc()}")
                action = dict(last)
            dt = time.perf_counter() - t0
            if dt > 0.03:
                slow += 1
                if slow <= 5 or slow % 50 == 0:
                    log(f"slow act {1000 * dt:.1f} ms at tick {latest.get('tick')} ({slow})")
        action["tick"] = latest["tick"]
        try:
            send(out, action)
        except (TypeError, ValueError):
            log(f"unserializable action at tick {latest['tick']}:\n{traceback.format_exc()}")
            send(out, {"tick": latest["tick"], **last})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "main")
