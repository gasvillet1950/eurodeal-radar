import os
from datetime import datetime, timedelta
from supabase import create_client
from fast_flights import FlightData, Passengers, Result, get_flights
from config import DESTINATIONS, ORIGINS, DEAL_THRESHOLD

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def clean_price(price):
    if price is None:
        return None
    try:
        return float(str(price).replace("$", "").replace("€", "").replace(",", "").strip())
    except ValueError:
        return None


def get_average_price(origin, destination):
    result = supabase.table("price_history").select("price").eq("origin", origin).eq("destination", destination).execute()
    prices = [r["price"] for r in result.data if r["price"]]
    if not prices:
        return None
    return sum(prices) / len(prices)


def save_price_history(origin, destination, price):
    supabase.table("price_history").insert({
        "origin": origin,
        "destination": destination,
        "price": clean_price(price),
    }).execute()


def compute_deal_score(price, avg_price):
    if not avg_price:
        return 0
    return round((avg_price - price) / avg_price, 4)


def save_flight_deal(origin, dest, city, price, dep_date, ret_date, airline, deal_type, score):
    supabase.table("flights_deals").insert({
        "origin": origin,
        "destination": dest,
        "city_name": city,
        "price": clean_price(price),
        "departure_date": str(dep_date),
        "return_date": str(ret_date),
        "airline": airline,
        "deal_type": deal_type,
        "deal_score": score,
    }).execute()


def fetch_flights(origin, destination, dep_date, ret_date, one_day=False):
    try:
        if one_day:
            flight_data = [
                FlightData(date=dep_date.strftime("%Y-%m-%d"), from_airport=origin, to_airport=destination),
            ]
            trip = "one-way"
        else:
            flight_data = [
                FlightData(date=dep_date.strftime("%Y-%m-%d"), from_airport=origin, to_airport=destination),
                FlightData(date=ret_date.strftime("%Y-%m-%d"), from_airport=destination, to_airport=origin),
            ]
            trip = "round-trip"

        result: Result = get_flights(
            flight_data=flight_data,
            trip=trip,
            seat="economy",
            passengers=Passengers(adults=1),
            fetch_mode="fallback",
        )
        if result and result.flights:
            return result.flights
        return []
    except Exception as e:
        print(f"Erreur fetch {origin}→{destination} : {e}")
        return []


def process_weekend_deals():
    print("→ Deals week-end...")
    today = datetime.today()
    weekends = []
    for i in range(60):
        d = today + timedelta(days=i)
        if d.weekday() == 4:
            weekends.append((d.date(), (d + timedelta(days=2)).date()))

    for origin in ORIGINS:
        for dest in DESTINATIONS:
            avg = get_average_price(origin, dest["iata"])
            for dep, ret in weekends[:4]:
                dep_dt = datetime.combine(dep, datetime.min.time())
                ret_dt = datetime.combine(ret, datetime.min.time())
                flights = fetch_flights(origin, dest["iata"], dep_dt, ret_dt)
                for f in flights[:1]:
                    price = clean_price(f.price)
                    if price is None:
                        continue
                    save_price_history(origin, dest["iata"], price)
                    score = compute_deal_score(price, avg)
                    if avg is None or score >= DEAL_THRESHOLD:
                        airline = getattr(f, "name", "N/A")
                        save_flight_deal(origin, dest["iata"], dest["city"], price, dep, ret, airline, "weekend", score)
                        print(f"  ✅ Deal week-end : {origin}→{dest['iata']} {dep} {price}€ score:{score}")


def process_oneday_deals():
    print("→ Deals 1 jour...")
    today = datetime.today()
    weekenddays = []
    for i in range(180):
        d = today + timedelta(days=i)
        if d.weekday() in [5, 6]:
            weekenddays.append(d.date())

    for origin in ORIGINS:
        for dest in DESTINATIONS:
            avg = get_average_price(origin, dest["iata"])
            for day in weekenddays[:8]:
                dep_dt = datetime.combine(day, datetime.min.time())
                flights = fetch_flights(origin, dest["iata"], dep_dt, dep_dt, one_day=True)
                for f in flights[:1]:
                    price = clean_price(f.price)
                    if price is None:
                        continue
                    save_price_history(origin, dest["iata"], price)
                    score = compute_deal_score(price, avg)
                    if avg is None or score >= DEAL_THRESHOLD:
                        airline = getattr(f, "name", "N/A")
                        save_flight_deal(origin, dest["iata"], dest["city"], price, day, day, airline, "1jour", score)
                        print(f"  ✅ Deal 1 jour : {origin}→{dest['iata']} {day} {price}€")


def process_best_deals():
    print("→ Meilleurs deals globaux...")
    today = datetime.today()
    for origin in ORIGINS:
        for dest in DESTINATIONS:
            avg = get_average_price(origin, dest["iata"])
            dep = today + timedelta(days=30)
            ret = dep + timedelta(days=3)
            flights = fetch_flights(origin, dest["iata"], dep, ret)
            for f in flights[:1]:
                price = clean_price(f.price)
                if price is None:
                    continue
                save_price_history(origin, dest["iata"], price)
                score = compute_deal_score(price, avg)
                if avg is None or score >= DEAL_THRESHOLD:
                    airline = getattr(f, "name", "N/A")
                    save_flight_deal(origin, dest["iata"], dest["city"], price, dep.date(), ret.date(), airline, "best", score)
                    print(f"  ✅ Meilleur deal : {origin}→{dest['iata']} {price}€")


if __name__ == "__main__":
    print("🚀 Eurodeal Radar — démarrage fetcher")
    process_weekend_deals()
    process_oneday_deals()
    process_best_deals()
    print("✅ Fetcher terminé")
