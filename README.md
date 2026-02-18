# QR Loyalty Demo (δοκιμαστικό)

Μικρό demo loyalty: **στα 5 scans → 1 δώρο**, με απλό anti-abuse (**1 scan ανά 30''** ανά χρήστη).

## Τρέξιμο (local)

```bash
cd qr_loyalty_demo
python app.py
```

Άνοιξε:
- http://127.0.0.1:5000/?user=demo

## Endpoints
- `/` αρχική με QR
- `/qr?user=demo` εικόνα QR που οδηγεί στο scan
- `/scan?user=demo` προσθέτει 1 σφραγίδα
- `/status?user=demo` κατάσταση
- `/redeem?user=demo` εξαργύρωση (όταν υπάρχει δώρο)
- `/admin/reset?user=demo` reset demo

## Σημείωση
Για πραγματική παραγωγή προτείνεται **QR μιας χρήσης (dynamic token)** στο ταμείο.
