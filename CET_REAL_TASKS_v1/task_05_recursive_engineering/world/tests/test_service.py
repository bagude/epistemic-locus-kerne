import unittest,json,hmac,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.webhook_service import WebhookService
def sig(secret,body): return hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
class Tests(unittest.TestCase):
    def test_valid_invoice_paid(self):
        secret='abc'; body=json.dumps({'id':'evt-1','type':'invoice.paid'}); s=WebhookService(secret)
        out=s.handle({'X-Signature':sig(secret,body)},body)
        self.assertEqual(out['status'],'ok'); self.assertEqual(s.store.counters['invoice_paid'],1)
if __name__=='__main__': unittest.main()
