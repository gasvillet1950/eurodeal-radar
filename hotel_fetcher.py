import os
import sys
import requests
import time
from datetime import datetime, timedelta
from supabase import create_client
from config import DESTINATIONS, MAX_HOTEL_PRICE, MIN_HOTEL_RATING

print("🏨 Démarrage hotel fetcher", flush=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

print(f"Connexion Supabase...", flush=True)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
print("✅ Supabase connecté", flush=True)

XOTELO_LIST = "https://data.xotelo.com/api/list"
XOTELO_RATES = "https://data.xotelo.com/api/rates"

# Génère les week-ends des 3 prochains mois
def get_upcoming_weekends(n=6):
    weekends = []
    today = datetime.today()
    for i in range(90):
        d = today + timedelta(days=i)
        if d.weekday() == 4:  # Vendredi
            checkin = d.strftime("%Y-%m-%d")
            checkout = (d + timedelta(days=2)).strftime("%Y-%m-%d")
            weekends.append((checkin, checkout))
            if len(weekends) >= n:
                break
    return weekends

def fetch_hotels(location_key):
    try:
        r = requests.get(XOTELO_LIST, params={
            "location_key": location_key,
            "limit": 15,
            "offset": 0
        }, timeout=8)
        data = r.json()
        if data.get("error") or not data.get("result"):
            return []
        return data["result"].get("list", [])
    except Exception as e:
        print(f"  Erreur liste: {e}", flush=True)
        return []

def fetch_rates(hotel_key, checkin, checkout):
    try:
        r = requests.get(XOTELO_RATES, params={
            "hotel_key": hotel_key,
            "chk_in": checkin,
            "chk_out": checkout,
        }, timeout=8)
        data = r.json()
        if data.get("error") or not data.get("result"):
            return None
        return data["result"].get("rates", [])
    except Exception as e:
        print(f"  Erreur rates: {e}", flush=True)
        return None

def best_rate(rates):
    if not rates:
        return None, None, None
    valid = [r for r in rates if r.get("rate") and float(r["rate"]) > 0]
    if not valid:
        return None, None, None
    # Priorité Booking
    for r in valid:
        if "booking" in r.get("name","").lower():
            return float(r["rate"]), r.get("name","Booking.com"), r.get("url","")
    best = min(valid, key=lambda x: float(x["rate"]))
    return float(best["rate"]), best.get("name","N/A"), best.get("url","")

def nights(checkin, checkout):
    try:
        return max(1,(datetime.strptime(checkout,"%Y-%m-%d")-datetime.strptime(checkin,"%Y-%m-%d")).days)
    except:
        return 2

def already_exists(iata, checkin, hotel_key):
    r = supabase.table("hotels_deals").select("id")\
        .eq("destination",iata).eq("checkin_date",checkin)\
        .eq("hotel_key",hotel_key).limit(1).execute()
    return len(r.data) > 0

def booking_fallback(city, checkin, checkout):
    c = city.replace(" ","+")
    return f"https://www.booking.com/searchresults.html?ss={c}&checkin={checkin}&checkout={checkout}&group_adults=2&no_rooms=1&nflt=review_score%3D80"

weekends = get_upcoming_weekends(6)
print(f"→ {len(weekends)} week-ends à traiter", flush=True)

for dest in DESTINATIONS:
    iata = dest["iata"]
    city = dest["city"]
    loc_key = dest.get("xotelo_key")
    if not loc_key:
        continue

    print(f"\n📍 {city}...", flush=True)
    hotels = fetch_hotels(loc_key)

    if not hotels:
        print(f"  ⚠️ Aucun hôtel", flush=True)
        continue

    # Filtre par note ≥ MIN_HOTEL_RATING
    good = [h for h in hotels if h.get("review_summary",{}).get("rating",0) >= MIN_HOTEL_RATING]
    print(f"  → {len(good)} hôtels bien notés sur {len(hotels)}", flush=True)

    if not good:
        continue

    for checkin, checkout in weekends:
        n = nights(checkin, checkout)
        saved = 0

        for hotel in good:
            if saved >= 2:
                break

            hkey = hotel.get("key","")
            hname = hotel.get("name","?")
            hrating = hotel.get("review_summary",{}).get("rating",0)
            hurl = hotel.get("url","")

            if not hkey:
                continue
            if already_exists(iata, checkin, hkey):
                saved += 1
                continue

            rates = fetch_rates(hkey, checkin, checkout)
            price, source, rate_url = best_rate(rates)
            time.sleep(0.2)

            if price is None or price > MAX_HOTEL_PRICE:
                continue

            url = rate_url or hurl or booking_fallback(city, checkin, checkout)
            total = round(price * n, 2)

            supabase.table("hotels_deals").insert({
                "city_name": city,
                "destination": iata,
                "hotel_name": hname,
                "price_per_night": price,
                "total_price": total,
                "nights": n,
                "rating": hrating,
                "checkin_date": checkin,
                "checkout_date": checkout,
                "url": url,
                "hotel_key": hkey,
                "source": source or "N/A",
            }).execute()

            saved += 1
            print(f"  ✅ {hname} | {checkin} | {price}€/nuit | {source}", flush=True)

        time.sleep(0.3)

print("\n✅ Hotel fetcher terminé", flush=True)
