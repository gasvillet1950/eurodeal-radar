import os
import requests
from supabase import create_client

print("🏨 Diagnostic Xotelo", flush=True)

# Test plusieurs formats possibles de location_key
test_keys = [
    ("Barcelone", "g187497"),
    ("Barcelone alt", "187497"),
    ("Paris ref", "g187147"),  # Paris connu
    ("Tokyo ref", "g14129735"),  # Tokyo connu
]

XOTELO_LIST = "https://data.xotelo.com/api/list"

for name, key in test_keys:
    print(f"\n--- Test: {name} (key={key}) ---", flush=True)
    try:
        r = requests.get(XOTELO_LIST, params={
            "location_key": key,
            "limit": 3,
            "offset": 0
        }, timeout=10)
        print(f"Status HTTP: {r.status_code}", flush=True)
        print(f"Réponse brute (500 premiers caractères):", flush=True)
        print(r.text[:500], flush=True)
    except Exception as e:
        print(f"Erreur: {e}", flush=True)

print("\n✅ Diagnostic terminé", flush=True)
