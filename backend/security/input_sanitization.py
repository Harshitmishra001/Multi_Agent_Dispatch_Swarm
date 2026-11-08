import re

def sanitize_report_text(raw_text: str) -> str:
    """
    Primary defense against prompt injection from untrusted user input.
    Since we wrap user input in <raw_text> tags for the LLM, we must
    ensure the user cannot close those tags prematurely.
    """
    if not raw_text:
        return ""
        
    # Strip any attempt to close or open our delimiter tags iteratively
    # to defend against nested tag bypasses (e.g., <<raw_text>/raw_text>)
    pattern = re.compile(r'<\s*/?\s*raw_text\s*>', re.IGNORECASE)
    sanitized = raw_text
    while pattern.search(sanitized):
        sanitized = pattern.sub('', sanitized)
    
    # We could also limit length here, but Pydantic already does max_length=2000
    return sanitized.strip()
