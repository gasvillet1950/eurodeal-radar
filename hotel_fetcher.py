import os
import requests
import time
from datetime import datetime
from supabase import create_client
from config import DESTINATIONS, MAX_HOTEL_PRICE, MIN_HOTEL_RATING

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

XOTELO_LIST = "https://data.xotelo.com/api/list"
XOTELO_RATES = "https://data.xotelo.com/api/rates"


def get_flight_date_pairs():
    """Récupère toutes les combinaisons uniques (iata, checkin, checkout) depuis les deals week-end et best"""
    result = supabase.table("flights_deals")\
        .select("destination, departure_date, return_date")\
        .in_("deal_type", ["weekend", "best"])\
        .execute()

    seen = set()
    pairs = []
    for row in result.data:
        dest = row["destination"]
        dep = row["departure_date"]
        ret = row["return_date"]
        if not dep or not ret or dep == ret:
            continue
        key = f"{dest}-{dep}-{ret}"
        if key not in seen:
            seen.add(key)
            pairs.append({
                "iata": dest,
                "checkin": dep,
                "checkout": ret,
            })
    print(f"  → {len(pairs)} combinaisons ville/dates trouvées")
    return pairs


def get_xotelo_key(iata):
    """Retourne la clé Xotelo pour un code IATA"""
    for d in DESTINATIONS:
        if d["iata"] == iata:
            return d.get("xotelo_key")
    return None


def get_city_name(iata):
    for d in DESTINATIONS:
        if d["iata"] == iata:
            return d["city"]
    return iata


def fetch_hotels_for_location(location_key, limit=20):
    """Récupère la liste des hôtels d'une ville via Xotelo"""
    try:
        r = requests.get(XOTELO_LIST, params={
            "location_key": location_key,
            "limit": limit,
            "offset": 0
        }, timeout=10)
        data = r.json()
        if data.get("error") or not data.get("result"):
            return []
        hotels = data["result"].get("list", [])
        # Filtre : hôtels uniquement (pas hostels/auberges)
        hotels = [h for h in hotels if h.get("accommodation_type", "").lower() in ["hotel", "hôtel", ""]]
        return hotels
    except Exception as e:
        print(f"    Erreur liste hôtels {location_key}: {e}")
        return []


def fetch_hotel_rates(hotel_key, checkin, checkout):
    """Récupère les prix d'un hôtel pour des dates données"""
    try:
        r = requests.get(XOTELO_RATES, params={
            "hotel_key": hotel_key,
            "chk_in": checkin,
            "chk_out": checkout,
        }, timeout=10)
        data = r.json()
        if data.get("error") or not data.get("result"):
            return None
        rates = data["result"].get("rates", [])
        if not rates:
            return None
        return rates
    except Exception as e:
        print(f"    Erreur rates {hotel_key}: {e}")
        return None


def get_best_rate(rates):
    """Retourne le meilleur prix Booking.com en premier, sinon le moins cher dispo"""
    if not rates:
        return None, None
    # Priorité Booking.com
    for r in rates:
        if "booking" in r.get("name", "").lower() or "booking" in r.get("code", "").lower():
            if r.get("rate") and r["rate"] > 0:
                return float(r["rate"]), r.get("name", "Booking.com")
    # Sinon le moins cher
    valid = [r for r in rates if r.get("rate") and r["rate"] > 0]
    if not valid:
        return None, None
    best = min(valid, key=lambda x: x["rate"])
    return float(best["rate"]), best.get("name", "N/A")


def build_booking_url(city_name, checkin, checkout):
    """Génère un lien Booking.com de secours"""
    city_encoded = city_name.replace(" ", "+").replace("è", "e").replace("é", "e")
    return f"https://www.booking.com/searchresults.html?ss={city_encoded}&checkin={checkin}&checkout={checkout}&group_adults=2&no_rooms=1&order=price"


def nights_between(checkin, checkout):
    try:
        d1 = datetime.strptime(checkin, "%Y-%m-%d")
        d2 = datetime.strptime(checkout, "%Y-%m-%d")
        return max(1, (d2 - d1).days)
    except:
        return 1


def already_saved(iata, checkin, checkout, hotel_key):
    """Vérifie si ce deal hôtel existe déjà en base"""
    result = supabase.table("hotels_deals")\
        .select("id")\
        .eq("destination", iata)\
        .eq("checkin_date", checkin)\
        .eq("checkout_date", checkout)\
        .eq("hotel_key", hotel_key)\
        .limit(1)\
        .execute()
    return len(result.data) > 0


def process_hotels():
    print("→ Fetching hotel deals...")
    pairs = get_flight_date_pairs()

    for pair in pairs:
        iata = pair["iata"]
        checkin = pair["checkin"]
        checkout = pair["checkout"]
        city = get_city_name(iata)
        location_key = get_xotelo_key(iata)

        if not location_key:
            continue

        n_nights = nights_between(checkin, checkout)

        # Récupère les hôtels de la ville
        hotels = fetch_hotels_for_location(location_key, limit=30)
        if not hotels:
            print(f"  ⚠️ Aucun hôtel trouvé pour {city}")
            continue

        # Filtre par note
        good_hotels = [
            h for h in hotels
            if h.get("review_summary", {}).get("rating", 0) >= MIN_HOTEL_RATING
        ]

        if not good_hotels:
            print(f"  ⚠️ Aucun hôtel noté ≥{MIN_HOTEL_RATING} pour {city}")
            continue

        saved_count = 0

        for hotel in good_hotels:
            if saved_count >= 2:
                break

            hotel_key = hotel.get("key")
            hotel_name = hotel.get("name", "N/A")
            hotel_rating = hotel.get("review_summary", {}).get("rating", 0)
            hotel_url = hotel.get("url", "")

            if not hotel_key:
                continue

            if already_saved(iata, checkin, checkout, hotel_key):
                saved_count += 1
                continue

            # Récupère les prix
            rates = fetch_hotel_rates(hotel_key, checkin, checkout)
            price_per_night, source = get_best_rate(rates)

            if price_per_night is None:
                continue

            # Filtre prix max
            if price_per_night > MAX_HOTEL_PRICE:
                continue

            total = round(price_per_night * n_nights, 2)

            # Lien direct : TripAdvisor si dispo, sinon Booking
            direct_url = hotel_url if hotel_url else build_booking_url(city, checkin, checkout)

            # Sauvegarde
            supabase.table("hotels_deals").insert({
                "city_name": city,
                "destination": iata,
                "hotel_name": hotel_name,
                "price_per_night": price_per_night,
                "total_price": total,
                "nights": n_nights,
                "rating": hotel_rating,
                "checkin_date": checkin,
                "checkout_date": checkout,
                "url": direct_url,
                "hotel_key": hotel_key,
                "source": source or "N/A",
            }).execute()

            saved_count += 1
            print(f"  ✅ {city} {checkin}→{checkout} | {hotel_name} | {price_per_night}€/nuit | note:{hotel_rating} | {source}")

            time.sleep(0.3)

        time.sleep(0.5)

    print("✅ Hotel fetcher terminé")


if __name__ == "__main__":
    print("🏨 Eurodeal Radar — démarrage hotel fetcher")
    process_hotels()
