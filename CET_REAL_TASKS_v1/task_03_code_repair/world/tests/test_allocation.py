import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.allocation import Invoice, allocate_payment
class Tests(unittest.TestCase):
    def test_oldest_first_unsorted(self):
        x=[Invoice('new','2026-08-20',5000),Invoice('old','2026-08-01',7000)]
        self.assertEqual(allocate_payment(x,8000),({'new':4000,'old':0},0))
    def test_partial(self):
        self.assertEqual(allocate_payment([Invoice('a','2026-08-01',10000)],2500),({'a':7500},0))
    def test_excess(self):
        x=[Invoice('a','2026-08-01',1000),Invoice('b','2026-08-02',2000)]
        self.assertEqual(allocate_payment(x,5000),({'a':0,'b':0},2000))
if __name__=='__main__': unittest.main()
