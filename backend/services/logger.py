import logging

log = logging.getLogger("reputonbot")
# базовая конфигурация, если её нет
if not log.handlers:
    log.setLevel(logging.INFO)
    h = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    h.setFormatter(fmt)
    log.addHandler(h)

__all__ = ["log"]
