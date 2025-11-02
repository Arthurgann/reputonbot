import logging, os, sys

def configure_json_logging():
    if os.getenv("LOG_JSON", "0") != "1":
        return
    lg = logging.getLogger("reputonbot")
    # снять старые хендлеры
    for h in list(lg.handlers):
        lg.removeHandler(h)
    h = logging.StreamHandler(sys.stdout)
    # ровно одна строка = message (мы печатаем JSON в log_event)
    h.setFormatter(logging.Formatter('%(message)s'))
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    lg.propagate = False   # важно: не отдавать наверх к root/uvicorn