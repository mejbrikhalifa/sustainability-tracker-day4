# ai_tips.py
import os
from dotenv import load_dotenv
import time
from functools import lru_cache
from openai import OpenAI, OpenAIError

# Create client (safe even if key is missing; we guard before calling)
load_dotenv()  # Load variables from .env if present
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Local factors used only for rules-based fallback logic.
# These mirror typical factors used elsewhere in the app, but are intentionally local
# so this module stays self-contained and never crashes due to imports.
LOCAL_CO2_FACTORS = {
    "electricity_kwh": 0.233,
    "natural_gas_m3": 2.03,
    "hot_water_liter": 0.25,
    "cold_water_liter": 0.075,
    "district_heating_kwh": 0.15,
    "propane_liter": 1.51,
    "fuel_oil_liter": 2.52,
    "petrol_liter": 0.235,
    "diesel_liter": 0.268,
    "bus_km": 0.12,
    "train_km": 0.14,
    "bicycle_km": 0.0,
    "flight_short_km": 0.275,
    "flight_long_km": 0.175,
    "meat_kg": 27.0,
    "chicken_kg": 6.9,
    "eggs_kg": 4.8,
    "dairy_kg": 13.0,
    "vegetarian_kg": 2.0,
    "vegan_kg": 1.5,
}

def generate_eco_tip(user_data: dict, emissions: float) -> str:
    """Public entry point used by the app. Tries GPT with caching and backoff;
    falls back to local rules if key missing or calls fail.
    """
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not set. Using local tip generator.")
        return clean_tip(local_tip(user_data, emissions))

    # Build a deterministic cache key from user_data
    try:
        user_key = ",".join(f"{k}={user_data.get(k, 0)}" for k in sorted(user_data.keys()))
    except Exception:
        user_key = str(sorted(user_data.items()))

    tip = _generate_eco_tip_cached(user_key, float(emissions or 0))
    if tip:
        return clean_tip(tip)
    return clean_tip(local_tip(user_data, emissions))


@lru_cache(maxsize=128)
def _generate_eco_tip_cached(user_data_key: str, emissions: float) -> str:
    """Cached GPT tip generator. Returns empty string on failure to signal fallback."""
    prompt = (
        """
        You are a helpful sustainability coach.

        User's daily activities: {user_data_summary}
        Total CO₂ emitted today: {emissions:.2f} kg

        Provide a concise, practical eco-friendly tip tailored to reduce their largest CO₂ source.
        Requirements:
        - Keep it positive and motivational.
        - Limit to 1–2 short sentences (or 1–2 bullet points max).
        - Prefer concrete, easy actions the user can do today or tomorrow.
        """.strip()
    ).format(user_data_summary=user_data_key, emissions=emissions)

    retries = 3
    base_delay = 1.0
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a sustainability assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=120,
                temperature=0.7,
            )
            return (response.choices[0].message.content or "").strip()
        except OpenAIError as e:
            # Retry on OpenAI API errors (rate limit/quota/etc.), then give up
            sleep_s = base_delay * (2 ** attempt)
            print(f"⚠️ GPT call failed (attempt {attempt+1}/{retries}): {e}. Retrying in {sleep_s:.1f}s...")
            time.sleep(sleep_s)
        except Exception as e:
            print(f"⚠️ Unexpected GPT error: {e}")
            break
    return ""


def local_tip(user_data: dict, emissions: float) -> str:
    """
    Simple rules-based fallback that never crashes and gives helpful, actionable tips.
    - Identifies the largest-emitting activity using LOCAL_CO2_FACTORS
    - Provides a targeted tip for that activity
    - Includes tiered guidance based on total emissions
    """
    # Largest emitter detection
    best_key = None
    best_kg = 0.0
    for k, amt in user_data.items():
        try:
            amt_f = float(amt or 0)
        except Exception:
            amt_f = 0.0
        factor = LOCAL_CO2_FACTORS.get(k)
        if factor is None:
            continue
        kg = amt_f * factor
        if kg > best_kg:
            best_kg = kg
            best_key = k

    # Tiered guidance based on total emissions
    if emissions > 60:
        preface = "🚨 High footprint today."
    elif emissions > 25:
        preface = "🌱 Moderate footprint today."
    else:
        preface = "🌍 Low footprint today—nice work!"

    # Targeted, practical suggestions
    tips_by_key = {
        # Energy
        "electricity_kwh": "Reduce standby power: switch devices fully off, use smart strips, and swap to LED bulbs.",
        "natural_gas_m3": "Lower heating setpoint by 1°C and seal drafts to cut gas use.",
        "hot_water_liter": "Take shorter showers and wash clothes on cold to cut hot water.",
        "cold_water_liter": "Fix leaks and install low‑flow faucets to save water and energy.",
        "district_heating_kwh": "Use a programmable thermostat and improve insulation to reduce heat demand.",
        "propane_liter": "Service your boiler and optimize thermostat schedules to trim propane use.",
        "fuel_oil_liter": "Schedule a boiler tune‑up and improve home insulation to cut oil use.",
        # Transport
        "petrol_liter": "Try car‑pooling or public transport 1–2 days/week; keep tires properly inflated.",
        "diesel_liter": "Combine errands into one trip and ease acceleration to save fuel.",
        "bus_km": "Great choice using the bus—consider a weekly pass to keep it going.",
        "train_km": "Nice! Train is low‑carbon—can you replace a short car trip with train?",
        "bicycle_km": "Awesome cycling—aim to replace one short car errand by bike this week.",
        "flight_short_km": "Consider rail for short trips, or bundle meetings to reduce flight frequency.",
        "flight_long_km": "Plan fewer long‑haul flights; if needed, choose non‑stop routes and economy seats.",
        # Meals
        "meat_kg": "Try a meat‑free day or swap red meat for chicken/plant‑based options.",
        "chicken_kg": "Balance meals with beans, lentils, and seasonal veggies a few times this week.",
        "eggs_kg": "Source from local farms and add plant‑based proteins to diversify.",
        "dairy_kg": "Switch to plant milk for coffee/tea and try dairy‑free snacks.",
        "vegetarian_kg": "Great! Add pulses and whole grains for protein and nutrition.",
        "vegan_kg": "Excellent! Keep variety with legumes, nuts, and B12‑fortified foods.",
    }

    if best_key and best_key in tips_by_key and best_kg > 0:
        return f"{preface} Biggest source: {best_key.replace('_', ' ')}. Tip: {tips_by_key[best_key]}"

    # Otherwise choose a general practical tip based on broad categories
    energy_load = sum((float(user_data.get(k, 0) or 0)) * LOCAL_CO2_FACTORS.get(k, 0) for k in [
        "electricity_kwh", "natural_gas_m3", "district_heating_kwh", "propane_liter", "fuel_oil_liter"
    ])
    transport_load = sum((float(user_data.get(k, 0) or 0)) * LOCAL_CO2_FACTORS.get(k, 0) for k in [
        "petrol_liter", "diesel_liter", "bus_km", "train_km", "flight_short_km", "flight_long_km"
    ])
    meals_load = sum((float(user_data.get(k, 0) or 0)) * LOCAL_CO2_FACTORS.get(k, 0) for k in [
        "meat_kg", "chicken_kg", "dairy_kg", "eggs_kg"
    ])

    if transport_load >= energy_load and transport_load >= meals_load and transport_load > 0:
        return f"{preface} Transport dominates—plan a no‑car day, try car‑pooling, or take the bus/train for one commute."
    if energy_load >= transport_load and energy_load >= meals_load and energy_load > 0:
        return f"{preface} Energy dominates—set heating 1–2°C lower and switch off devices fully at night."
    if meals_load > 0:
        return f"{preface} Diet is a big lever—try a meat‑free day and batch‑cook plant‑based meals this week."

    # Final generic tip
    return f"{preface} Start small: one meat‑free meal, one public‑transport trip, and switch devices fully off tonight."


def clean_tip(tip: str, max_sentences: int = 2) -> str:
    """Trim whitespace and limit the tip to a maximum number of sentences.
    Keeps the content concise for the UI.
    """
    if not isinstance(tip, str):
        return ""
    tip = tip.strip()
    if not tip:
        return tip
    # Split on periods while preserving basic punctuation
    parts = [p.strip() for p in tip.split('.') if p.strip()]
    if len(parts) > max_sentences:
        tip = '. '.join(parts[:max_sentences]).strip() + '.'
    return tip