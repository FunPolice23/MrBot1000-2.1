"""Provider-value normalization helpers for the legacy worker layer."""


def normalize_keep_alive(value) -> object:
    """Normalize Ollama keep-alive values to accepted forms."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    value_text = str(value).strip()
    if value_text == "":
        return None
    if value_text in ("-1", "0"):
        return int(value_text)
    if value_text.lstrip("-").isdigit():
        return value_text + "s"
    return value_text


__all__ = ["normalize_keep_alive"]
