import json
from .store import EventStore
from .auth import verify_signature
class WebhookService:
    def __init__(self, secret, store=None): self.secret=secret; self.store=store or EventStore()
    def handle(self, headers, body):
        verify_signature(self.secret, body, headers.get('X-Signature',''))  # result ignored
        event=json.loads(body); event_id=event['id']
        self.store.append(event_id,event)  # duplicates processed again
        if event.get('type')=='invoice.paid': self.store.increment_counter('invoice_paid')
        return {'status':'ok','event_id':event_id}
