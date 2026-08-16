class EventStore:
    def __init__(self): self.events=[]; self.counters={}
    def append(self,event_id,event): self.events.append((event_id,event))
    def increment_counter(self,key): self.counters[key]=self.counters.get(key,0)+1
