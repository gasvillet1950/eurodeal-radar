import streamlit as st
from supabase import create_client
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Eurodeal Radar", page_icon="✈️", layout="wide")
st.title("✈️ Eurodeal Radar")
st.caption("Tes meilleurs deals vols Europe depuis Paris")

tab1, tab2, tab3, tab4 = st.tabs(["🗓️ Deals 1 jour", "📅 Deals week-end", "🏆 Meilleurs deals", "🏨 Hôtels bientôt"])

def load_deals(deal_type):
    result = supabase.table("flights_deals")\
        .select("*")\
        .eq("deal_type", deal_type)\
        .order("price", desc=False)\
        .limit(50)\
        .execute()
    return result.data

def display_deals(deals):
    if not deals:
        st.info("Aucun deal détecté pour l'instant. Reviens dans quelques heures !")
        return
    for d in deals:
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            st.markdown(f"**{d['origin']} → {d['city_name']}**")
            st.caption(f"{d['airline']}")
        with col2:
            st.markdown(f"🛫 {d['departure_date']}")
            st.markdown(f"🛬 {d['return_date']}")
        with col3:
            st.markdown(f"💶 **{d['price']}€**")
            score = d.get('deal_score', 0) or 0
            if score >= 0.15:
                st.success(f"🔥 -{round(score*100)}% vs prix moyen")
        with col4:
            st.markdown(f"`{d['destination']}`")
        st.divider()

with tab1:
    st.subheader("Vols aller-retour en 1 journée de week-end")
    deals = load_deals("1jour")
    display_deals(deals)

with tab2:
    st.subheader("Vols du vendredi au dimanche")
    deals = load_deals("weekend")
    display_deals(deals)

with tab3:
    st.subheader("Les prix les plus bas toutes dates confondues")
    deals = load_deals("best")
    display_deals(deals)

with tab4:
    st.info("🏨 Section hôtels en cours de développement — bientôt disponible !")
