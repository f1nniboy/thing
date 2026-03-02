def clean_for_display(text: str, max_len: int = 120) -> str:
    """Strip formatting, collapse whitespace, and truncate for display."""
    text = " ".join(text.replace("`", "").replace("*", "").replace("> ", "").split())
    return text if len(text) <= max_len else text[:max_len].rstrip() + "…"
