import re
PII = [re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)]
def minimize(text: str) -> str:
    for rx in PII: text = rx.sub("[redacted-email]", text)
    return text
