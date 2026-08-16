from dataclasses import dataclass
@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    due_date: str
    balance: int

def allocate_payment(invoices, payment_cents):
    remaining = {i.invoice_id: i.balance for i in invoices}
    cash = payment_cents
    # BUG: caller order + incorrect cash propagation.
    for inv in invoices:
        if cash <= 0: break
        remaining[inv.invoice_id] -= cash
        cash = max(0, -remaining[inv.invoice_id])
        remaining[inv.invoice_id] = max(0, remaining[inv.invoice_id])
    return remaining, cash
