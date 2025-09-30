# app.py
import os
import pandas as pd
import datetime as dt
import streamlit as st
import io
from co2_engine import calculate_co2, CO2_FACTORS, calculate_co2_breakdown
from utils import (
    format_emissions as fmt_emissions,
    friendly_message as status_message,
    percentage_change,
)
from ai_tips import generate_eco_tip as ai_generate_eco_tip
import time
import concurrent.futures
import csv

# Set page config first (must be the first Streamlit command)
st.set_page_config(page_title="Sustainability Tracker", page_icon="🌍", layout="wide")

# =========================
# Category Mapping & Storage
# =========================
CATEGORY_MAP = {
    "Energy": [
        "electricity_kwh",
        "natural_gas_m3",
        "hot_water_liter",
        "cold_water_liter",
        "district_heating_kwh",
        "propane_liter",
        "fuel_oil_liter",
    ],
    "Transport": [
        "petrol_liter",
        "diesel_liter",
        "bus_km",
        "train_km",
        "bicycle_km",
        "flight_short_km",
        "flight_long_km",
    ],
    "Meals": [
        "meat_kg",
        "chicken_kg",
        "eggs_kg",
        "dairy_kg",
        "vegetarian_kg",
        "vegan_kg",
    ],
}
ALL_KEYS = [k for keys in CATEGORY_MAP.values() for k in keys]

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.csv")


# =========================
# Helper Functions
# =========================
def compute_category_emissions(activity_data: dict) -> dict:
    result = {}
    for cat, keys in CATEGORY_MAP.items():
        subtotal = 0.0
        for k in keys:
            amt = float(activity_data.get(k, 0) or 0)
            factor = CO2_FACTORS.get(k)
            if factor is not None:
                subtotal += amt * factor
        result[cat] = round(subtotal, 2)
    return result


def load_history() -> pd.DataFrame:
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE, parse_dates=["date"])
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def save_entry(date_val: dt.date, activity_data: dict, total: float):
    df = load_history()
    row = {"date": pd.to_datetime(date_val)}
    for k in ALL_KEYS:
        row[k] = float(activity_data.get(k, 0) or 0)
    row["total_kg"] = float(total)

    if df.empty:
        df = pd.DataFrame([row])
    else:
        mask = df["date"].dt.date == date_val
        if mask.any():
            # Upsert
            df.loc[mask, list(row.keys())] = list(row.values())
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    df = df.sort_values("date")
    df.to_csv(HISTORY_FILE, index=False)


def get_yesterday_total(df: pd.DataFrame, date_val: dt.date) -> float:
    if df.empty:
        return 0.0
    yesterday = pd.to_datetime(date_val) - pd.Timedelta(days=1)
    mask = df["date"].dt.date == yesterday.date()
    if mask.any():
        return float(df.loc[mask, "total_kg"].iloc[0])
    return 0.0


def compute_streak(df: pd.DataFrame, date_val: dt.date) -> int:
    """Compute the current streak of consecutive days up to date_val."""
    if df.empty:
        return 0

    # Ensure all dates are datetime.date
    df_dates = df["date"].dt.date if pd.api.types.is_datetime64_any_dtype(df["date"]) else df["date"]
    dayset = set(df_dates)

    streak = 0
    current = date_val
    while current in dayset:
        streak += 1
        current -= dt.timedelta(days=1)

    return streak


def award_badges(today_total: float, streak: int, df: pd.DataFrame) -> list:
    badges = []
    if not df.empty:
        badges.append("📅 Consistency: Entries logged!")
    if today_total < 20:
        badges.append("🌿 Low Impact Day (< 20 kg)")
    if streak >= 3:
        badges.append("🔥 3-Day Streak")
    if streak >= 7:
        badges.append("🏆 7-Day Streak")
    if not df.empty:
        recent = df.tail(7)
        avg7 = float(recent["total_kg"].mean()) if not recent.empty else 0.0
        if avg7 and today_total < 0.9 * avg7:
            badges.append("📈 10% Better than 7-day avg")
    return badges


# =========================
# Streamlit App
# =========================
def main():
    # Density + header
    # Initialize persisted UI density in session state
    if "density" not in st.session_state:
        st.session_state["density"] = "Compact"

    # Read density from URL query params if present (new API)
    try:
        qp_density = st.query_params.get("density")
        if qp_density in ("Compact", "Comfy") and qp_density != st.session_state["density"]:
            st.session_state["density"] = qp_density
    except Exception:
        pass

    # Density toggle: Compact vs Comfy
    dens_col1, dens_col2 = st.columns([3, 1])
    with dens_col1:
        st.title("Sustainability Tracker 🌍")
        st.caption("Track daily CO₂ emissions and get actionable tips")
    with dens_col2:
        st.radio(
            "Density",
            ["Compact", "Comfy"],
            index=0 if st.session_state.get("density", "Compact") == "Compact" else 1,
            horizontal=True,
            key="density",
        )
        with st.popover("Export PDF tips"):
            st.markdown(
                """
                - Set Layout to **Landscape**
                - Set Scale to **75–85%**
                - Set Margins to **Narrow**
                - Ensure expanders are **collapsed** (Compact density) to reduce height
                - Use the **Download history CSV** button for data export
                """
            )
        # Help popover with a short FAQ
        with st.popover("Help"):
            st.markdown(
                """
                - **How are emissions calculated?** Using standard factors per activity (kg CO₂ per unit).
                - **Why is bicycle 0?** Cycling has negligible direct CO₂ emissions in this model.
                - **How do I save/export?** Click "Calculate & Save" then download the CSV in Dashboard.
                - **Tips to reduce CO₂?** See the Eco tip card and focus on your biggest source first.
                
                <br/>
                <a href="#secrets" style="text-decoration:none;">
                  <span style="display:inline-block;padding:2px 8px;border-radius:12px;background:#eef;border:1px solid #ccd;color:#223;">🔐 Secrets (README)</span>
                </a>
                <div style="font-size:0.9em;color:#555;">Configure your OPENAI_API_KEY via <code>.env</code>. See README → Secrets.</div>
                """,
                unsafe_allow_html=True,
            )
        # Hidden debug controls
        with st.expander("Debug (performance)", expanded=False):
            default_th = st.session_state.get("spinner_threshold", 0.3)
            th = st.slider("Spinner threshold (seconds)", 0.0, 2.0, float(default_th), 0.05)
            st.session_state["spinner_threshold"] = float(th)
            st.checkbox(
                "Enable performance logging (perf_log.csv)",
                value=st.session_state.get("perf_logging", False),
                key="perf_logging",
                help="Append eco-tip generation timings to perf_log.csv",
            )
            st.markdown(
                """
                <a href="#secrets" style="text-decoration:none;">
                  <span style="display:inline-block;padding:2px 8px;border-radius:12px;background:#eef;border:1px solid #ccd;color:#223;">🔐 Secrets (README)</span>
                </a>
                <div style="font-size:0.9em;color:#555;">Configure your OPENAI_API_KEY via <code>.env</code>. See README → Secrets.</div>
                """,
                unsafe_allow_html=True,
            )
        # Copy shareable link button (copies current URL with density param)
        st.markdown(
            """
            <button id=\"copy-link-btn\" style=\"margin-top:0.25rem;\">Copy shareable link</button>
            <script>
            const btn = document.getElementById('copy-link-btn');
            if (btn) {
              btn.addEventListener('click', async () => {
                try {
                  await navigator.clipboard.writeText(window.location.href);
                  const old = btn.textContent;
                  btn.textContent = 'Copied!';
                  setTimeout(() => { btn.textContent = old; }, 1500);
                } catch (e) {
                  btn.textContent = 'Copy failed';
                  setTimeout(() => { btn.textContent = 'Copy shareable link'; }, 1500);
                }
              });
            }
            </script>
            """,
            unsafe_allow_html=True,
        )
        # Reset layout button: revert to Compact density and update URL
        if st.button("Reset layout", type="secondary"):
            st.session_state["density"] = "Compact"
            try:
                st.query_params["density"] = "Compact"
            except Exception:
                pass
            st.experimental_rerun()
        # Clear inputs button: zero all input fields
        if st.button("Clear inputs", help="Reset all fields to zero for today’s entry."):
            try:
                for _k in ALL_KEYS:
                    _sk = f"in_{_k}"
                    if _sk in st.session_state:
                        st.session_state[_sk] = 0.0
            except Exception:
                pass
            st.experimental_rerun()
        # Demo and preset fillers
        with st.popover("Prefill demos/presets"):
            st.markdown("Pick a scenario to quickly populate inputs for demos.")
            c_demo, c_p1, c_p2 = st.columns(3)
            def _apply_values(vals: dict):
                for k, v in vals.items():
                    sk = f"in_{k}"
                    st.session_state[sk] = float(v)
                st.experimental_rerun()
            with c_demo:
                if st.button("Demo values"):
                    _apply_values({
                        # Energy
                        "electricity_kwh": 8,
                        "natural_gas_m3": 1.2,
                        "hot_water_liter": 60,
                        # Transport
                        "bus_km": 10,
                        "train_km": 0,
                        "petrol_liter": 2.5,
                        # Meals
                        "meat_kg": 0.15,
                        "dairy_kg": 0.3,
                        "vegetarian_kg": 0.2,
                    })
            with c_p1:
                if st.button("No car day"):
                    _apply_values({
                        "petrol_liter": 0,
                        "diesel_liter": 0,
                        "bus_km": 12,
                        "train_km": 6,
                        "bicycle_km": 5,
                    })
            with c_p2:
                if st.button("Vegetarian day"):
                    _apply_values({
                        "meat_kg": 0,
                        "chicken_kg": 0,
                        "vegetarian_kg": 0.6,
                        "vegan_kg": 0.2,
                        "dairy_kg": 0.25,
                    })
            c_p3, _, _ = st.columns(3)
            with c_p3:
                if st.button("Business trip"):
                    _apply_values({
                        "flight_short_km": 600,
                        "train_km": 20,
                        "electricity_kwh": 6,
                        "meat_kg": 0.25,
                    })

    # IMPORTANT: assign density BEFORE using it below
    density = st.session_state["density"]

    # Update URL query param to reflect current density (new API)
    try:
        st.query_params["density"] = density
    except Exception:
        pass

    # Heights and paddings based on density
    if density == "Compact":
        pad_top, pad_bottom = "1rem", "1rem"
        table_height = 150
        trend_height = 180
        bar_height = 180
        per_activity_height = 260
        expander_default = False
    else:
        pad_top, pad_bottom = "2rem", "2rem"
        table_height = 220
        trend_height = 260
        bar_height = 260
        per_activity_height = 360
        expander_default = True

    # Hide Streamlit default menu, footer, and header for cleaner PDF export
    st.markdown(
        f"""
        <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}
        .block-container {{padding-top: {pad_top}; padding-bottom: {pad_bottom};}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Top row: date and action area
    top_c1, top_c2 = st.columns([1, 2])
    with top_c1:
        selected_date = st.date_input("Date", value=dt.date.today())
    with top_c2:
        st.write("")

    with st.form("daily_input"):
        # Inputs grouped in compact expanders (density controlled)
        with st.expander("Energy inputs", expanded=expander_default):
            e1, e2, e3 = st.columns(3)
            with e1:
                electricity = st.number_input("Electricity (kWh)", value=0.0, min_value=0.0, step=0.1, key="in_electricity_kwh")
                natural_gas = st.number_input("Natural Gas (m³)", value=0.0, min_value=0.0, step=0.1, key="in_natural_gas_m3")
            with e2:
                hot_water = st.number_input("Hot Water (L)", value=0.0, min_value=0.0, step=1.0, key="in_hot_water_liter")
                cold_water = st.number_input("Cold/Chilled Water (L)", value=0.0, min_value=0.0, step=1.0, key="in_cold_water_liter")
            with e3:
                district_heating = st.number_input("District Heating (kWh)", value=0.0, min_value=0.0, step=0.1, key="in_district_heating_kwh")
                propane = st.number_input("Propane (L)", value=0.0, min_value=0.0, step=0.1, key="in_propane_liter")
                fuel_oil = st.number_input("Fuel Oil (L)", value=0.0, min_value=0.0, step=0.1, key="in_fuel_oil_liter")

        with st.expander("Transport inputs", expanded=expander_default):
            t1, t2, t3 = st.columns(3)
            with t1:
                petrol = st.number_input("Car Petrol (L)", value=0.0, min_value=0.0, step=0.1, key="in_petrol_liter")
                diesel = st.number_input("Car Diesel (L)", value=0.0, min_value=0.0, step=0.1, key="in_diesel_liter")
            with t2:
                bus = st.number_input("Bus (km)", value=0.0, min_value=0.0, step=1.0, key="in_bus_km")
                train = st.number_input("Train (km)", value=0.0, min_value=0.0, step=1.0, key="in_train_km")
                bicycle = st.number_input("Bicycle (km)", value=0.0, min_value=0.0, step=1.0, key="in_bicycle_km")
            with t3:
                flight_short = st.number_input("Flight Short (km)", value=0.0, min_value=0.0, step=1.0, key="in_flight_short_km")
                flight_long = st.number_input("Flight Long (km)", value=0.0, min_value=0.0, step=1.0, key="in_flight_long_km")

        with st.expander("Meals inputs", expanded=expander_default):
            m1, m2, m3 = st.columns(3)
            with m1:
                meat = st.number_input("Meat (kg)", value=0.0, min_value=0.0, step=0.1, key="in_meat_kg")
                chicken = st.number_input("Chicken (kg)", value=0.0, min_value=0.0, step=0.1, key="in_chicken_kg")
            with m2:
                eggs = st.number_input("Eggs (kg)", value=0.0, min_value=0.0, step=0.1, key="in_eggs_kg")
                dairy = st.number_input("Dairy (kg)", value=0.0, min_value=0.0, step=0.1, key="in_dairy_kg")
            with m3:
                vegetarian = st.number_input("Vegetarian (kg)", value=0.0, min_value=0.0, step=0.1, key="in_vegetarian_kg")
                vegan = st.number_input("Vegan (kg)", value=0.0, min_value=0.0, step=0.1, key="in_vegan_kg")

        submitted = st.form_submit_button("Calculate & Save")

    # Gather input into a dict compatible with CO2_FACTORS
    user_data = {
        "electricity_kwh": electricity,
        "natural_gas_m3": natural_gas,
        "hot_water_liter": hot_water,
        "cold_water_liter": cold_water,
        "district_heating_kwh": district_heating,
        "propane_liter": propane,
        "fuel_oil_liter": fuel_oil,
        "petrol_liter": petrol,
        "diesel_liter": diesel,
        "bus_km": bus,
        "train_km": train,
        "bicycle_km": bicycle,
        "flight_short_km": flight_short,
        "flight_long_km": flight_long,
        "meat_kg": meat,
        "chicken_kg": chicken,
        "eggs_kg": eggs,
        "dairy_kg": dairy,
        "vegetarian_kg": vegetarian,
        "vegan_kg": vegan,
    }

    # Calculate total emissions
    emissions = calculate_co2(user_data)

    # Compute per-activity once for optional breakdown tab
    per_activity = calculate_co2_breakdown(user_data)

    # Load history for KPIs and visuals
    history_df = load_history()
    yesterday_total = get_yesterday_total(history_df, selected_date)
    delta_pct = percentage_change(yesterday_total, emissions)
    streak = compute_streak(history_df, selected_date)

    # KPIs (compact)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", fmt_emissions(emissions))
    c2.metric("Δ vs. Yesterday", f"{delta_pct:.2f}%")
    c3.metric("Streak", f"{streak} day(s)")

    # Tabs for Dashboard and Breakdown
    tab_dashboard, tab_breakdown = st.tabs(["Dashboard", "Breakdown"])

    with tab_dashboard:
        # Two-column layout for compact one-page UI
        left_col, right_col = st.columns([2, 1])

        with left_col:
            # Category-wise table
            cat_emissions = compute_category_emissions(user_data)
            st.caption("Category totals (kg CO₂)")
            st.dataframe(
                pd.DataFrame.from_dict(cat_emissions, orient="index", columns=["kg CO₂"]),
                use_container_width=True,
                height=table_height,
            )

            st.caption("Today's category breakdown")
            st.bar_chart(pd.Series(cat_emissions, name="kg CO₂"), height=bar_height)

        with right_col:
            # Save after calculation
            if submitted:
                save_entry(selected_date, user_data, emissions)
                st.success("Saved.")

            # Visualizations (reduced height)
            history_df = load_history()  # reload after potential save
            if not history_df.empty:
                st.caption("Trend (Total kg CO₂)")
                history_df_display = history_df.copy()
                history_df_display["date"] = history_df_display["date"].dt.date
                st.line_chart(history_df_display.set_index("date")["total_kg"], height=trend_height)

                # CSV export button
                csv_buf = io.StringIO()
                history_df.to_csv(csv_buf, index=False)
                st.download_button(
                    label="⬇️ Download history CSV",
                    data=csv_buf.getvalue(),
                    file_name="history.csv",
                    mime="text/csv",
                )

            # Eco tip and status (compact)
            st.caption("Eco tip & status")
            start_time = time.time()
            placeholder = st.empty()
            tip = None
            threshold = float(st.session_state.get("spinner_threshold", 0.3))
            # Run tip generation in a background thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(ai_generate_eco_tip, user_data, emissions)
                spinner_shown = False
                # Poll until done; when threshold reached, block within spinner context
                while True:
                    if fut.done():
                        tip = fut.result()
                        break
                    elapsed_loop = time.time() - start_time
                    if not spinner_shown and elapsed_loop > threshold:
                        with placeholder.container():
                            with st.spinner("Generating eco-tip..."):
                                tip = fut.result()  # wait until complete while spinner shows
                        spinner_shown = True
                        break
                    time.sleep(0.05)
            elapsed = time.time() - start_time
            st.info(tip)
            st.caption(f"Tip generated in {elapsed:.2f}s")
            # Optional perf logging
            if st.session_state.get("perf_logging", False):
                log_path = os.path.join(os.getcwd(), "perf_log.csv")
                file_exists = os.path.exists(log_path)
                try:
                    with open(log_path, mode="a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(["timestamp", "elapsed_s", "emissions_kg"])  # header
                        writer.writerow([dt.datetime.now().isoformat(), f"{elapsed:.4f}", f"{emissions:.4f}"])
                except Exception as _e:
                    st.caption("Perf log: unable to write to perf_log.csv")
            st.success(status_message(emissions))

            # Badges (compact list)
            st.caption("Badges")
            badges = award_badges(emissions, streak, history_df)
            if badges:
                for b in badges:
                    st.markdown(f"- {b}")
            else:
                st.write("Log entries to start earning badges!")

        # Second row: mini sparklines by category
        if not history_df.empty:
            st.divider()
            st.caption("Mini trends by category")

            def _category_series(df: pd.DataFrame, keys: list[str]) -> pd.Series | None:
                present = [k for k in keys if k in df.columns]
                if not present:
                    return None
                s = pd.Series(0.0, index=df.index)
                for k in present:
                    factor = CO2_FACTORS.get(k, 0.0)
                    s = s + df[k].fillna(0).astype(float) * factor
                return s

            def _seven_day_delta(s: pd.Series):
                if s is None or s.empty:
                    return None, None
                s = s.dropna()
                if len(s) < 2:
                    return None, None
                last7 = float(s.iloc[-7:].sum())
                prev7 = float(s.iloc[-14:-7].sum()) if len(s) >= 14 else 0.0
                return last7, percentage_change(prev7, last7)

            df_sorted = history_df.sort_values("date").copy()
            df_sorted_indexed = df_sorted.set_index("date")

            energy_s = _category_series(df_sorted, CATEGORY_MAP["Energy"]) 
            energy_s = energy_s if (energy_s is not None and not energy_s.empty) else pd.Series(dtype=float)
            transport_s = _category_series(df_sorted, CATEGORY_MAP["Transport"]) 
            transport_s = transport_s if (transport_s is not None and not transport_s.empty) else pd.Series(dtype=float)
            meals_s = _category_series(df_sorted, CATEGORY_MAP["Meals"]) 
            meals_s = meals_s if (meals_s is not None and not meals_s.empty) else pd.Series(dtype=float)

            mini_height = 120 if density == "Compact" else 160
            c_en, c_tr, c_me = st.columns(3)
            with c_en:
                st.markdown("**Energy**")
                if not energy_s.empty:
                    st.line_chart(energy_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    en_last7, en_pct = _seven_day_delta(energy_s)
                    if en_last7 is not None:
                        st.metric("7d total", f"{en_last7:.2f} kg", f"{en_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")
            with c_tr:
                st.markdown("**Transport**")
                if not transport_s.empty:
                    st.line_chart(transport_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    tr_last7, tr_pct = _seven_day_delta(transport_s)
                    if tr_last7 is not None:
                        st.metric("7d total", f"{tr_last7:.2f} kg", f"{tr_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")
            with c_me:
                st.markdown("**Meals**")
                if not meals_s.empty:
                    st.line_chart(meals_s.set_axis(df_sorted_indexed.index), height=mini_height)
                    me_last7, me_pct = _seven_day_delta(meals_s)
                    if me_last7 is not None:
                        st.metric("7d total", f"{me_last7:.2f} kg", f"{me_pct:.1f}%", delta_color="inverse")
                    else:
                        st.caption("Not enough data yet")
                else:
                    st.write("No data yet")

    with tab_breakdown:
        st.caption("Per-activity emissions (kg CO₂)")
        if per_activity:
            st.dataframe(
                pd.Series(per_activity, name="kg CO₂").sort_values(ascending=False).to_frame(),
                use_container_width=True,
                height=per_activity_height,
            )
        else:
            st.info("No per-activity data to show yet.")


if __name__ == "__main__":
    main()