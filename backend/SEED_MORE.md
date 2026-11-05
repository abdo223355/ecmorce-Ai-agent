# More test data (made by novacart_backend.seed_more)

Same demo password as the other accounts (see SEED_SCENARIOS.md). Nothing existing was changed.

New customers: c-100201 .. c-100205 (each with a name, phone, address and login).
Customers c-100001 .. c-100010 and c-100201 .. c-100205 each got 10 more orders: Pending, Confirmed, Processing,
Packed, Shipped (due tomorrow), Out for Delivery (due today), two Delivered (one is a phone), Failed Delivery, Cancelled,
and returns on the delivered ones cycling through Requested, Approved, Rejected, Picked Up, Received, Refunded.

Workers w-2001 .. w-2005 each got 12 shipments: due TODAY (3 Out for Delivery, 1 Shipped, 2 Delivered, 1 Failed),
2 due tomorrow, one delivered 5 hours ago (inside the 24 h access window) and one delivered 40 hours ago (outside it).

Shipments due today in the whole database now: 128
