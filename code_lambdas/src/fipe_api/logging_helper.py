import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log_structured(status, event, details=None, error_type=None):
    """
    Log estruturado em JSON para observabilidade.

    Args:
        status: "START", "END", "SUCCESS", "ERROR", "WARNING"
        event: Descrição do evento
        details: Dict com detalhes adicionais
        error_type: Tipo de erro (para STATUS=ERROR)
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "event": event,
    }

    if error_type:
        log_entry["error_type"] = error_type

    if details:
        log_entry["details"] = details

    logger.info(json.dumps(log_entry))
