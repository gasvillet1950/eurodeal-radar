import os
import re
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
        return float(str(price).replace("$","").replace("€","").replace(",","").strip())
    except ValueError:
        return None


def clean_time(t):
    if not t:
        return None
    return str(t).strip()[:30]


def get_average_price(origin, destination):
    result = supabase.table("price_history").select("price")\
        .eq("origin", origin).eq("destination", destination).execute()
    prices = [r["price"] for r in result.data if r["price"]]
    return sum(prices) / len(prices) if prices else None


def save_price_history(origin, destination, price):
    supabase.table("price_history").insert({
        "origin": origin, "destination": destination, "price": price
    }).execute()


def compute_deal_score(price, avg_price):
    if not avg_price:
        return 0
    return round((avg_price - price) / avg_price, 4)


def save_flight_deal(origin, dest, city, price, dep_date, ret_date, airline,
                     deal_type, score, departure_time=None, arrival_time=None,
                     duration=None, stops=0,
                     return_departure_time=None, return_arrival_time=None):
    supabase.table("flights_deals").insert({
        "origin": origin, "destination": dest, "city_name": city,
        "price": price, "departure_date": str(dep_date), "return_date": str(ret_date),
        "airline": airline, "deal_type": deal_type, "deal_score": score,
        "departure_time": departure_time, "arrival_time": arrival_time,
        "duration": duration, "stops": stops,
        "return_departure_time": return_departure_time,
        "return_arrival_time": return_arrival_time,
    }).execute()


def extract_info(f):
    dep = clean_time(getattr(f, 'departure', None))
    arr = clean_time(getattr(f, 'arrival', None))
    dur = clean_time(getattr(f, 'duration', None))
    raw = getattr(f, 'stops', 0)
    try:
        stops = int(raw)
    except:
        stops = 0
    airline = getattr(f, 'name', None) or getattr(f, 'airline', 'N/A')
    return dep, arr, dur, stops, airline


def fetch_ow(origin, destination, date):
    try:
        result: Result = get_flights(
            flight_data=[FlightData(date=date.strftime("%Y-%m-%d"), from_airport=origin, to_airport=destination)],
            trip="one-way", seat="economy",
            passengers=Passengers(adults=1), fetch_mode="fallback",
        )
        if result and result.flights:
            return result.flights[0]
        return None
    except Exception as e:
        print(f"    Erreur OW {origin}→{destination}: {e}")
        return None


def fetch_rt(origin, destination, dep_date, ret_date):
    try:
        result: Result = get_flights(
            flight_data=[
                FlightData(date=dep_date.strftime("%Y-%m-%d"), from_airport=origin, to_airport=destination),
                FlightData(date=ret_date.strftime("%Y-%m-%d"), from_airport=destination, to_airport=origin),
            ],
            trip="round-trip", seat="economy",
            passengers=Passengers(adults=1), fetch_mode="fallback",
        )
        if result and result.flights:
            return result.flights
        return []
    except Exception as e:
        print(f"    Erreur RT {origin}→{destination}: {e}")
        return []


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
            for day in weekenddays[:4]:
                dep_dt = datetime.combine(day, datetime.min.time())

                f_out = fetch_ow(origin, dest["iata"], dep_dt)
                if not f_out:
                    continue

                dep_t, arr_t, dur, stops, airline = extract_info(f_out)
                price_out = clean_price(f_out.price)
                if price_out is None:
                    continue

                f_ret = fetch_ow(dest["iata"], origin, dep_dt)
                if not f_ret:
                    continue

                ret_dep_t = clean_time(getattr(f_ret, 'departure', None))
                ret_arr_t = clean_time(getattr(f_ret, 'arrival', None))
                price_ret = clean_price(f_ret.price)
                if price_ret is None:
                    continue

                price = round(price_out + price_ret, 2)
                save_price_history(origin, dest["iata"], price)
                score = compute_deal_score(price, avg)
                if avg is None or score >= DEAL_THRESHOLD:
                    save_flight_deal(
                        origin, dest["iata"], dest["city"], price, day, day,
                        airline, "1jour", score,
                        dep_t, arr_t, dur, stops,
                        ret_dep_t, ret_arr_t
                    )
                    print(f"  ✅ 1J {origin}→{dest['iata']} {day} {price}€ | ✈ {dep_t}→{arr_t} | ↩ {ret_dep_t}→{ret_arr_t}")


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
            for dep, ret in weekends[:2]:
                flights = fetch_rt(origin, dest["iata"],
                    datetime.combine(dep, datetime.min.time()),
                    datetime.combine(ret, datetime.min.time()))
                if not flights:
                    continue

                f_out = flights[0]
                f_ret = flights[1] if len(flights) > 1 else None
                price = clean_price(f_out.price)
                if price is None:
                    continue

                dep_t, arr_t, dur, stops, airline = extract_info(f_out)
                ret_dep_t = clean_time(getattr(f_ret, 'departure', None)) if f_ret else None
                ret_arr_t = clean_time(getattr(f_ret, 'arrival', None)) if f_ret else None

                save_price_history(origin, dest["iata"], price)
                score = compute_deal_score(price, avg)
                if avg is None or score >= DEAL_THRESHOLD:
                    save_flight_deal(origin, dest["iata"], dest["city"], price, dep, ret,
                                     airline, "weekend", score,
                                     dep_t, arr_t, dur, stops, ret_dep_t, ret_arr_t)
                    print(f"  ✅ WE {origin}→{dest['iata']} {dep} {price}€ | ✈ {dep_t}→{arr_t} | ↩ {ret_dep_t}→{ret_arr_t}")


def process_best_deals():
    print("→ Meilleurs deals globaux...")
    today = datetime.today()
    for origin in ORIGINS:
        for dest in DESTINATIONS:
            avg = get_average_price(origin, dest["iata"])
            dep = today + timedelta(days=30)
            ret = dep + timedelta(days=3)
            flights = fetch_rt(origin, dest["iata"], dep, ret)
            if not flights:
                continue
            f_out = flights[0]
            f_ret = flights[1] if len(flights) > 1 else None
            price = clean_price(f_out.price)
            if price is None:
                continue
            dep_t, arr_t, dur, stops, airline = extract_info(f_out)
            ret_dep_t = clean_time(getattr(f_ret, 'departure', None)) if f_ret else None
            ret_arr_t = clean_time(getattr(f_ret, 'arrival', None)) if f_ret else None
            save_price_history(origin, dest["iata"], price)
            score = compute_deal_score(price, avg)
            if avg is None or score >= DEAL_THRESHOLD:
                save_flight_deal(origin, dest["iata"], dest["city"], price, dep.date(), ret.date(),
                                 airline, "best", score,
                                 dep_t, arr_t, dur, stops, ret_dep_t, ret_arr_t)
                print(f"  ✅ Best {origin}→{dest['iata']} {price}€ | ✈ {dep_t}→{arr_t} | ↩ {ret_dep_t}→{ret_arr_t}")


if __name__ == "__main__":
    print("🚀 Eurodeal Radar — démarrage fetcher")
    process_weekend_deals()
    process_oneday_deals()
    process_best_deals()
    print("✅ Fetcher terminé")
