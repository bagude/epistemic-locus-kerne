import hmac, hashlib
def verify_signature(secret,body,supplied):
    expected=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,supplied)
