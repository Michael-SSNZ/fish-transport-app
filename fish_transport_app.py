import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
import io
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# ----- Configuration -----
TANKER_CONFIGS = {
    "Mackenzies": {
        "Tank 1": 4700,
        "Tank 2": 5400,
        "Tank 3": 5900,
        "Tank 4": 8200
    },
    "Sanford": {
        "Tank 1": 3000,
        "Tank 2": 3000,
        "Tank 3": 3000,
        "Tank 4": 3000,
        "Tank 5": 7000
    }
}

# Recommended density ranges (kg/m³)
DENSITY_WARNING_THRESHOLD = 80
DENSITY_CRITICAL_THRESHOLD = 100

st.set_page_config(page_title="Fish Transport Allocation", layout="wide")

st.title("🐟 Fish Transport Allocation Tool")
st.write("This tool distributes fish across tanks based on tank volume to achieve equal or custom density (kg/m³).")

# ----- Sidebar for Settings -----
with st.sidebar:
    st.header("⚙️ Settings")

    # Tanker selection
    st.subheader("🚛 Tanker Selection")
    selected_tanker = st.selectbox(
        "Select tanker",
        options=list(TANKER_CONFIGS.keys()),
        index=0
    )

    # Display tanker info
    st.info(f"**{selected_tanker}**\n\n" +
            "\n".join([f"- {tank}: {vol:,}L" for tank, vol in TANKER_CONFIGS[selected_tanker].items()]))

    st.divider()

    # Tank configuration option
    st.subheader("Tank Configuration")
    use_custom_tanks = st.checkbox("Customize tank volumes", value=False)

    if use_custom_tanks:
        tanks = {}
        for tank_name, default_vol in TANKER_CONFIGS[selected_tanker].items():
            tanks[tank_name] = st.number_input(
                f"{tank_name} volume (L)",
                min_value=100,
                value=default_vol,
                key=f"vol_{tank_name}"
            )
    else:
        tanks = TANKER_CONFIGS[selected_tanker].copy()

    st.divider()

    # Boat capacity constraint
    st.subheader("🚢 Boat Capacity Limit")
    use_boat_capacity = st.checkbox("Limit by destination boat capacity", value=False,
                                     help="Constrain tanker load to match boat's receiving tank capacity")

    boat_max_volume = None
    num_boat_tanks = None
    boat_tank_size = None

    if use_boat_capacity:
        col_boat1, col_boat2 = st.columns(2)
        with col_boat1:
            num_boat_tanks = st.number_input("Number of boat tanks", min_value=1, max_value=10, value=3, step=1)
        with col_boat2:
            boat_tank_size = st.number_input("Boat tank size (L)", min_value=100, value=6000, step=100)

        boat_max_volume = num_boat_tanks * boat_tank_size
        st.info(f"🚢 Boat capacity: {num_boat_tanks} × {boat_tank_size:,}L = **{boat_max_volume:,}L total**")

    st.divider()

    # Density thresholds
    st.subheader("Density Alerts")
    warning_threshold = st.number_input("Warning threshold (kg/m³)", min_value=1, value=DENSITY_WARNING_THRESHOLD)
    critical_threshold = st.number_input("Critical threshold (kg/m³)", min_value=1, value=DENSITY_CRITICAL_THRESHOLD)

# ----- Main Input Section -----
st.subheader("🐠 Fish Weight Configuration")

# Option to use same weight or different weights
weight_mode = st.radio(
    "Fish weight mode",
    options=["Same weight for all tanks", "Different weights per tank"],
    horizontal=True
)

fish_weights = {}

if weight_mode == "Same weight for all tanks":
    default_weight = st.number_input("Fish weight (grams)", min_value=1.0, value=60.0, step=5.0)
    for tank_name in tanks.keys():
        fish_weights[tank_name] = default_weight
else:
    st.write("**Set fish weight for each tank:**")

    # Create columns for better layout
    num_tanks = len(tanks)
    cols_per_row = 3

    tank_list = list(tanks.keys())
    for i in range(0, num_tanks, cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < num_tanks:
                tank_name = tank_list[i + j]
                with cols[j]:
                    fish_weights[tank_name] = st.number_input(
                        f"{tank_name} (grams)",
                        min_value=1.0,
                        value=60.0,
                        step=5.0,
                        key=f"weight_{tank_name}"
                    )

st.divider()

# Boat capacity constraint display
if use_boat_capacity and boat_max_volume:
    st.info(f"🚢 **Boat Capacity Constraint Active:** Tanker will be limited to {boat_max_volume:,}L to match boat receiving capacity ({num_boat_tanks} tanks × {boat_tank_size:,}L)")

st.divider()

# Transport details
st.subheader("📦 Delivery Configuration")

delivery_mode = st.radio(
    "Delivery type",
    options=["Single delivery", "Multi-day deliveries"],
    horizontal=True
)

if delivery_mode == "Single delivery":
    total_fish = st.number_input("Total number of fish to transport", min_value=1, value=30000, step=100)
    num_deliveries = 1
    fish_per_delivery = total_fish

else:  # Multi-day deliveries
    col1, col2 = st.columns(2)

    with col1:
        total_fish_all = st.number_input("Total fish to deliver (all days)", min_value=1, value=110000, step=1000)

    with col2:
        num_deliveries = st.number_input("Number of deliveries", min_value=2, max_value=10, value=3, step=1)

    # Calculate fish per delivery
    fish_per_delivery = total_fish_all // num_deliveries
    remainder = total_fish_all % num_deliveries

    st.info(f"📊 **Delivery breakdown:** {fish_per_delivery:,} fish per delivery (×{num_deliveries} deliveries = {fish_per_delivery * num_deliveries:,} total)" +
            (f" + {remainder:,} fish in final delivery" if remainder > 0 else ""))

    total_fish = fish_per_delivery

# ----- Allocation Strategy -----
st.subheader("📐 Allocation Strategy")

allocation_mode = st.radio(
    "How should fish be allocated?",
    options=["Equal density across all tanks", "Manual allocation per tank", "Plan by destination tank requirements"],
    horizontal=True
)

# Handle destination tank planning
if allocation_mode == "Plan by destination tank requirements":
    st.write("**Step 1: Specify destination tank requirements**")

    destination_requirements = {}
    cols_per_row = 3

    # Create a list for destination tanks
    num_dest_tanks = st.number_input("Number of destination tanks", min_value=1, max_value=20, value=6, step=1)

    dest_tank_list = [f"Destination Tank {i+1}" for i in range(num_dest_tanks)]

    for i in range(0, len(dest_tank_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(dest_tank_list):
                tank_name = dest_tank_list[i + j]
                with cols[j]:
                    destination_requirements[tank_name] = st.number_input(
                        tank_name,
                        min_value=0,
                        value=21000 if i + j in [2, 3] else 0,  # Default 21k for tanks 3 and 4
                        step=100,
                        key=f"dest_{tank_name}"
                    )

    st.divider()

    # Map transport tanks to destination tanks
    st.write("**Step 2: Map transport tanks to destination tanks**")
    st.caption("Specify which transport tanks will be emptied into each destination tank")

    transport_to_dest_mapping = {}
    tank_list = list(tanks.keys())

    # For each destination tank that has fish requirements, show mapping options
    active_dest_tanks = [k for k, v in destination_requirements.items() if v > 0]

    for dest_tank in active_dest_tanks:
        st.write(f"**{dest_tank}** (needs {destination_requirements[dest_tank]:,} fish)")

        # Multi-select for transport tanks
        selected_transport_tanks = st.multiselect(
            f"Select transport tanks that will empty into {dest_tank}",
            options=tank_list,
            default=[],
            key=f"mapping_{dest_tank}"
        )

        if selected_transport_tanks:
            transport_to_dest_mapping[dest_tank] = selected_transport_tanks
            st.success(f"✓ {', '.join(selected_transport_tanks)} → {dest_tank}")
        else:
            st.warning(f"⚠️ No transport tanks assigned to {dest_tank}")

    st.divider()

    # Calculate allocation based on mapping
    if transport_to_dest_mapping:
        st.write("**Step 3: Calculated transport tank allocation**")

        # Initialize all transport tanks to 0
        calculated_allocations = {tank: 0 for tank in tank_list}

        # For each destination tank, divide its requirement among assigned transport tanks
        for dest_tank, transport_tanks in transport_to_dest_mapping.items():
            fish_needed = destination_requirements[dest_tank]
            num_transport_tanks = len(transport_tanks)

            if num_transport_tanks > 0:
                # Distribute based on volume ratios of assigned transport tanks
                total_assigned_volume = sum(tanks[t] for t in transport_tanks)

                for transport_tank in transport_tanks:
                    tank_volume = tanks[transport_tank]
                    # Allocate proportionally by volume
                    fish_for_this_tank = round(fish_needed * (tank_volume / total_assigned_volume))
                    calculated_allocations[transport_tank] += fish_for_this_tank

        # Show the allocation plan
        allocation_plan_data = []
        for tank_name, fish_count in calculated_allocations.items():
            if fish_count > 0:
                # Find which destination tanks this transport tank feeds
                dest_tanks_fed = [dest for dest, transports in transport_to_dest_mapping.items() if tank_name in transports]

                allocation_plan_data.append({
                    "Transport Tank": tank_name,
                    "Fish to Load": fish_count,
                    "Empties Into": ", ".join(dest_tanks_fed)
                })

        if allocation_plan_data:
            allocation_plan_df = pd.DataFrame(allocation_plan_data)
            st.dataframe(allocation_plan_df, use_container_width=True, hide_index=True)

            total_allocated = sum(calculated_allocations.values())
            total_required = sum(destination_requirements[k] for k in active_dest_tanks)

            st.info(f"📊 Total fish to load: {total_allocated:,} | Total required: {total_required:,} | Difference: {total_allocated - total_required:+,}")

        # Override total_fish with calculated allocation
        total_fish = sum(calculated_allocations.values())
    else:
        st.warning("⚠️ Please map transport tanks to destination tanks to continue")
        calculated_allocations = None

# ----- Calculations -----
total_volume = sum(tanks.values())

# Apply boat capacity constraint if enabled
effective_tanks = tanks.copy()
boat_capacity_warning = None

if use_boat_capacity and boat_max_volume:
    # Calculate which tanks to use based on boat capacity
    # Start filling from first tank until we reach boat capacity
    cumulative_volume = 0
    tanks_to_use = {}

    for tank_name, vol in tanks.items():
        if cumulative_volume + vol <= boat_max_volume:
            tanks_to_use[tank_name] = vol
            cumulative_volume += vol
        elif cumulative_volume < boat_max_volume:
            # Partial tank - only use what fits
            remaining_capacity = boat_max_volume - cumulative_volume
            tanks_to_use[tank_name] = remaining_capacity
            cumulative_volume = boat_max_volume
            boat_capacity_warning = f"⚠️ {tank_name} partially filled to {remaining_capacity:,}L (of {vol:,}L) to meet boat capacity limit"
            break

    effective_tanks = tanks_to_use
    effective_volume = sum(effective_tanks.values())

    if effective_volume < boat_max_volume:
        st.info(f"ℹ️ Using tanker tanks totaling {effective_volume:,}L (boat capacity allows {boat_max_volume:,}L)")

    if boat_capacity_warning:
        st.warning(boat_capacity_warning)
else:
    effective_volume = total_volume

allocations = []
density_alerts = []

if allocation_mode == "Plan by destination tank requirements" and calculated_allocations:
    # Use the calculated allocations from destination mapping
    for tank_name, vol in effective_tanks.items():
        fish_for_tank = calculated_allocations.get(tank_name, 0)
        biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
        density_kg_m3 = biomass_kg / (vol / 1000) if vol > 0 else 0

        # Check density
        if density_kg_m3 >= critical_threshold:
            status = "🔴 Critical"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Critical)")
        elif density_kg_m3 >= warning_threshold:
            status = "🟡 Warning"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Warning)")
        else:
            status = "🟢 OK"

        # Find destination info
        dest_info = ""
        if allocation_mode == "Plan by destination tank requirements":
            dest_tanks_fed = [dest for dest, transports in transport_to_dest_mapping.items() if tank_name in transports]
            if dest_tanks_fed:
                dest_info = ", ".join(dest_tanks_fed)

        allocations.append({
            "Tank": tank_name,
            "Volume (L)": vol,
            "Fish Weight (g)": fish_weights[tank_name],
            "Allocated Fish": fish_for_tank,
            "Biomass (kg)": round(biomass_kg, 2),
            "Density (kg/m³)": round(density_kg_m3, 2),
            "Status": status,
            "Destination": dest_info
        })

elif allocation_mode == "Equal density across all tanks":
    # Calculate weighted allocation based on volume and weight
    # For equal density: fish_count_i / volume_i * weight_i should be constant
    # So: fish_count_i = k * volume_i / weight_i
    # Where k is chosen so sum(fish_count_i) = total_fish

    weight_volume_ratios = {tank: effective_tanks[tank] / fish_weights[tank] for tank in effective_tanks.keys()}
    total_ratio = sum(weight_volume_ratios.values())

    for tank_name, vol in effective_tanks.items():
        fish_for_tank = round(total_fish * (weight_volume_ratios[tank_name] / total_ratio))
        biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
        density_kg_m3 = biomass_kg / (vol / 1000)

        # Check density
        if density_kg_m3 >= critical_threshold:
            status = "🔴 Critical"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Critical)")
        elif density_kg_m3 >= warning_threshold:
            status = "🟡 Warning"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Warning)")
        else:
            status = "🟢 OK"

        allocations.append({
            "Tank": tank_name,
            "Volume (L)": vol,
            "Fish Weight (g)": fish_weights[tank_name],
            "Allocated Fish": fish_for_tank,
            "Biomass (kg)": round(biomass_kg, 2),
            "Density (kg/m³)": round(density_kg_m3, 2),
            "Status": status
        })

else:  # Manual allocation
    st.write("**Set number of fish for each tank:**")

    manual_allocations = {}
    tank_list = list(effective_tanks.keys())
    cols_per_row = 3  # Define columns per row for manual allocation

    for i in range(0, len(tank_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(tank_list):
                tank_name = tank_list[i + j]
                with cols[j]:
                    manual_allocations[tank_name] = st.number_input(
                        f"{tank_name} fish count",
                        min_value=0,
                        value=int(total_fish * (effective_tanks[tank_name] / effective_volume)),
                        step=100,
                        key=f"manual_{tank_name}"
                    )

    # Calculate with manual allocations
    for tank_name, vol in effective_tanks.items():
        fish_for_tank = manual_allocations[tank_name]
        biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
        density_kg_m3 = biomass_kg / (vol / 1000) if vol > 0 else 0

        # Check density
        if density_kg_m3 >= critical_threshold:
            status = "🔴 Critical"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Critical)")
        elif density_kg_m3 >= warning_threshold:
            status = "🟡 Warning"
            density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Warning)")
        else:
            status = "🟢 OK"

        allocations.append({
            "Tank": tank_name,
            "Volume (L)": vol,
            "Fish Weight (g)": fish_weights[tank_name],
            "Allocated Fish": fish_for_tank,
            "Biomass (kg)": round(biomass_kg, 2),
            "Density (kg/m³)": round(density_kg_m3, 2),
            "Status": status
        })

    # Check if manual total matches
    manual_total = sum(manual_allocations.values())
    if manual_total != total_fish:
        st.warning(f"⚠️ Manual allocation total ({manual_total:,}) doesn't match target ({total_fish:,}). Difference: {manual_total - total_fish:+,}")

df = pd.DataFrame(allocations)

# Calculate actual totals from allocations
actual_total_fish = df["Allocated Fish"].sum()
actual_total_biomass = df["Biomass (kg)"].sum()

# ----- Alerts -----
if density_alerts:
    st.warning("⚠️ **Density Alerts:**\n\n" + "\n\n".join(density_alerts))

# ----- Summary Statistics -----
st.subheader("📊 Summary Statistics")
summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

with summary_col1:
    st.metric("Total Fish Allocated", f"{actual_total_fish:,}")

with summary_col2:
    st.metric("Total Biomass", f"{actual_total_biomass:,.2f} kg")

with summary_col3:
    st.metric("Average Density", f"{(actual_total_biomass / (effective_volume / 1000)):.2f} kg/m³")

with summary_col4:
    if use_boat_capacity and boat_max_volume:
        st.metric("Effective Volume (Boat Limit)", f"{effective_volume:,} L",
                  delta=f"{effective_volume - total_volume:+,} L" if effective_volume != total_volume else None,
                  help=f"Limited by boat capacity. Tanker total: {total_volume:,}L")
    else:
        st.metric("Total Volume", f"{total_volume:,} L")

# Additional metrics
metric_col1, metric_col2 = st.columns(2)

with metric_col1:
    st.metric("Selected Tanker", selected_tanker)

with metric_col2:
    avg_fish_weight = sum(df["Allocated Fish"] * df["Fish Weight (g)"]) / actual_total_fish if actual_total_fish > 0 else 0
    st.metric("Weighted Avg Fish Weight", f"{avg_fish_weight:.1f} g")

# Multi-day delivery summary
if delivery_mode == "Multi-day deliveries":
    st.divider()
    st.subheader("📅 Multi-Day Delivery Summary")

    delivery_summary_data = []
    for day in range(1, num_deliveries + 1):
        is_last = day == num_deliveries
        fish_this_delivery = fish_per_delivery + (remainder if is_last else 0)
        biomass_this_delivery = (fish_this_delivery / actual_total_fish) * actual_total_biomass if actual_total_fish > 0 else 0

        delivery_summary_data.append({
            "Delivery": f"Day {day}",
            "Fish Count": fish_this_delivery,
            "Biomass (kg)": round(biomass_this_delivery, 2),
            "Trips Required": 1,
            "Tank Allocation": "As shown above"
        })

    delivery_df = pd.DataFrame(delivery_summary_data)

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.dataframe(delivery_df, use_container_width=True, hide_index=True)

    with col_right:
        st.metric("Total Deliveries", num_deliveries)
        st.metric("Total Fish (All Days)", f"{total_fish_all:,}" if 'total_fish_all' in locals() else f"{actual_total_fish * num_deliveries:,}")
        st.metric("Total Biomass (All Days)", f"{actual_total_biomass * num_deliveries:,.2f} kg")

# Destination tank summary (if using that mode)
if allocation_mode == "Plan by destination tank requirements" and 'active_dest_tanks' in locals():
    st.divider()
    st.subheader("🎯 Offloading Plan")

    # Create offloading plan table
    offload_plan = []
    for dest_tank in active_dest_tanks:
        transport_tanks = transport_to_dest_mapping.get(dest_tank, [])
        fish_required = destination_requirements[dest_tank]

        # Calculate how much each transport tank contributes
        contributions = []
        for t_tank in transport_tanks:
            fish_in_tank = calculated_allocations.get(t_tank, 0)
            if fish_in_tank > 0:
                contributions.append(f"{t_tank} ({fish_in_tank:,})")

        offload_plan.append({
            "Destination Tank": dest_tank,
            "Required Fish": fish_required,
            "Transport Tanks": " + ".join(contributions) if contributions else "Not assigned",
            "Total Delivered": sum(calculated_allocations.get(t, 0) for t in transport_tanks)
        })

    offload_df = pd.DataFrame(offload_plan)

    col_dest_left, col_dest_right = st.columns([3, 1])

    with col_dest_left:
        st.dataframe(offload_df, use_container_width=True, hide_index=True)

    with col_dest_right:
        total_required = sum(destination_requirements[k] for k in active_dest_tanks)
        st.metric("Total Required", f"{total_required:,}")
        st.metric("Total Loaded", f"{actual_total_fish:,}")

        difference = actual_total_fish - total_required
        if difference == 0:
            st.success("✅ Exact match")
        elif abs(difference) < 100:
            st.info(f"≈ {difference:+,} difference")
        else:
            st.warning(f"⚠️ {difference:+,} difference")

    st.info("💡 **Offloading instructions:** Empty the transport tanks listed above into their corresponding destination tanks.")

# ----- Allocation Table -----
st.subheader("📋 Transport Tank Allocation")

# Show boat capacity limit info if active
if use_boat_capacity and boat_max_volume:
    tanks_used = list(effective_tanks.keys())
    tanks_excluded = [t for t in tanks.keys() if t not in effective_tanks]

    info_parts = [f"🚢 **Boat Capacity Mode:** Loading {effective_volume:,}L of {total_volume:,}L tanker capacity"]
    info_parts.append(f"**Tanks in use:** {', '.join(tanks_used)}")

    if tanks_excluded:
        info_parts.append(f"**Tanks excluded:** {', '.join(tanks_excluded)} (exceed boat capacity)")

    st.info(" | ".join(info_parts))

# Add percentage column
df["% of Total"] = round((df["Allocated Fish"] / actual_total_fish) * 100, 1) if actual_total_fish > 0 else 0

st.dataframe(df, use_container_width=True, hide_index=True)

# ----- Actual Fish Count Input -----
st.divider()
st.subheader("📝 Record Actual Loading")

record_actual = st.checkbox("Record actual fish counts loaded", value=False,
                            help="Enable this to input the actual number of fish loaded into each tank")

actual_fish_counts = {}
variance_data = []

if record_actual:
    st.write("**Enter the actual number of fish loaded into each tank:**")
    st.caption("This allows you to track variance between planned and actual loading")

    # Create input fields for actual counts
    tank_list = list(df["Tank"])
    cols_per_row = 3

    for i in range(0, len(tank_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(tank_list):
                tank_name = tank_list[i + j]
                target_count = int(df[df["Tank"] == tank_name]["Allocated Fish"].values[0])

                with cols[j]:
                    actual_fish_counts[tank_name] = st.number_input(
                        f"{tank_name} (Target: {target_count:,})",
                        min_value=0,
                        value=target_count,
                        step=100,
                        key=f"actual_{tank_name}"
                    )

    # Calculate variance
    st.divider()
    st.subheader("📊 Target vs Actual Comparison")

    for _, row in df.iterrows():
        tank_name = row["Tank"]
        target = row["Allocated Fish"]
        actual = actual_fish_counts.get(tank_name, target)
        variance = actual - target
        variance_pct = (variance / target * 100) if target > 0 else 0

        # Calculate actual biomass and density
        actual_biomass = actual * row["Fish Weight (g)"] / 1000
        actual_density = actual_biomass / (row["Volume (L)"] / 1000)

        variance_data.append({
            "Tank": tank_name,
            "Target Fish": target,
            "Actual Fish": actual,
            "Variance": variance,
            "Variance %": round(variance_pct, 1),
            "Target Density (kg/m³)": row["Density (kg/m³)"],
            "Actual Density (kg/m³)": round(actual_density, 2),
            "Status": "🟢 Match" if abs(variance_pct) < 5 else ("🟡 Minor" if abs(variance_pct) < 10 else "🔴 Major")
        })

    variance_df = pd.DataFrame(variance_data)

    # Show summary metrics
    total_target = df["Allocated Fish"].sum()
    total_actual = sum(actual_fish_counts.values())
    total_variance = total_actual - total_target
    total_variance_pct = (total_variance / total_target * 100) if total_target > 0 else 0

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    with metric_col1:
        st.metric("Target Total", f"{total_target:,}")

    with metric_col2:
        st.metric("Actual Total", f"{total_actual:,}")

    with metric_col3:
        st.metric("Total Variance", f"{total_variance:+,}",
                  delta=f"{total_variance_pct:+.1f}%")

    with metric_col4:
        if abs(total_variance_pct) < 5:
            st.metric("Overall Status", "🟢 Good")
        elif abs(total_variance_pct) < 10:
            st.metric("Overall Status", "🟡 Acceptable")
        else:
            st.metric("Overall Status", "🔴 Review")

    # Show variance table
    st.dataframe(variance_df, use_container_width=True, hide_index=True)

st.divider()

# ----- Visualizations -----
st.subheader("📈 Visualizations")

viz_col1, viz_col2 = st.columns(2)

with viz_col1:
    # Fish allocation bar chart
    fig_fish = px.bar(df, x="Tank", y="Allocated Fish",
                      title="Fish Allocation by Tank",
                      color="Density (kg/m³)",
                      color_continuous_scale="RdYlGn_r",
                      text="Allocated Fish",
                      hover_data=["Fish Weight (g)", "Biomass (kg)"])
    fig_fish.update_traces(texttemplate='%{text:,}', textposition='outside')
    fig_fish.update_layout(showlegend=False)
    st.plotly_chart(fig_fish, use_container_width=True)

with viz_col2:
    # Density comparison
    fig_density = go.Figure()

    colors_list = ['red' if d >= critical_threshold else 'orange' if d >= warning_threshold else 'green'
                   for d in df["Density (kg/m³)"]]

    fig_density.add_trace(go.Bar(
        x=df["Tank"],
        y=df["Density (kg/m³)"],
        marker_color=colors_list,
        text=df["Density (kg/m³)"],
        texttemplate='%{text:.2f}',
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>Density: %{y:.2f} kg/m³<extra></extra>'
    ))

    # Add threshold lines
    fig_density.add_hline(y=warning_threshold, line_dash="dash", line_color="orange",
                          annotation_text="Warning", annotation_position="right")
    fig_density.add_hline(y=critical_threshold, line_dash="dash", line_color="red",
                          annotation_text="Critical", annotation_position="right")

    fig_density.update_layout(
        title="Density by Tank (kg/m³)",
        yaxis_title="Density (kg/m³)",
        xaxis_title="Tank",
        showlegend=False
    )
    st.plotly_chart(fig_density, use_container_width=True)

# Biomass and fish weight comparison
viz_col3, viz_col4 = st.columns(2)

with viz_col3:
    # Pie chart for percentage distribution
    fig_pie = px.pie(df, values="Allocated Fish", names="Tank",
                     title="Fish Distribution Percentage",
                     hole=0.3)
    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
    st.plotly_chart(fig_pie, use_container_width=True)

with viz_col4:
    # Fish weight per tank
    fig_weight = px.bar(df, x="Tank", y="Fish Weight (g)",
                        title="Fish Weight by Tank",
                        text="Fish Weight (g)",
                        color="Fish Weight (g)",
                        color_continuous_scale="Blues")
    fig_weight.update_traces(texttemplate='%{text:.1f}g', textposition='outside')
    fig_weight.update_layout(showlegend=False)
    st.plotly_chart(fig_weight, use_container_width=True)

# Target vs Actual visualization (if actual counts are recorded)
if record_actual and variance_data:
    st.divider()
    st.subheader("📊 Target vs Actual Analysis")

    viz_var_col1, viz_var_col2 = st.columns(2)

    with viz_var_col1:
        # Target vs Actual bar chart
        fig_comparison = go.Figure()

        fig_comparison.add_trace(go.Bar(
            name='Target',
            x=variance_df["Tank"],
            y=variance_df["Target Fish"],
            marker_color='lightblue',
            text=variance_df["Target Fish"],
            texttemplate='%{text:,}',
            textposition='outside'
        ))

        fig_comparison.add_trace(go.Bar(
            name='Actual',
            x=variance_df["Tank"],
            y=variance_df["Actual Fish"],
            marker_color='darkblue',
            text=variance_df["Actual Fish"],
            texttemplate='%{text:,}',
            textposition='outside'
        ))

        fig_comparison.update_layout(
            title="Target vs Actual Fish Count",
            barmode='group',
            xaxis_title="Tank",
            yaxis_title="Fish Count",
            showlegend=True
        )
        st.plotly_chart(fig_comparison, use_container_width=True)

    with viz_var_col2:
        # Variance chart
        colors_variance = ['green' if abs(v) < 5 else 'orange' if abs(v) < 10 else 'red'
                           for v in variance_df["Variance %"]]

        fig_variance = go.Figure()
        fig_variance.add_trace(go.Bar(
            x=variance_df["Tank"],
            y=variance_df["Variance %"],
            marker_color=colors_variance,
            text=variance_df["Variance %"],
            texttemplate='%{text:+.1f}%',
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>Variance: %{y:+.1f}%<extra></extra>'
        ))

        fig_variance.add_hline(y=0, line_dash="solid", line_color="black", line_width=1)
        fig_variance.add_hline(y=5, line_dash="dash", line_color="orange", opacity=0.5)
        fig_variance.add_hline(y=-5, line_dash="dash", line_color="orange", opacity=0.5)

        fig_variance.update_layout(
            title="Variance % by Tank",
            xaxis_title="Tank",
            yaxis_title="Variance %",
            showlegend=False
        )
        st.plotly_chart(fig_variance, use_container_width=True)

# ----- Export Functions -----
def create_pdf(dataframe, tanker_name, tanks_dict, fish_weights_dict, total_fish, allocation_mode, delivery_mode_param="Single delivery", num_deliveries_param=1, total_fish_all_param=None, use_boat_capacity_param=False, boat_max_volume_param=None, num_boat_tanks_param=None, boat_tank_size_param=None, variance_dataframe=None):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Title
    c.setFont("Helvetica-Bold", 24)
    title = "Fish Transport Allocation Report"
    c.drawCentredString(width / 2, height - 60, title)

    # Timestamp
    c.setFont("Helvetica", 10)
    timestamp = datetime.now().strftime("Generated on %Y-%m-%d at %H:%M")
    c.drawCentredString(width / 2, height - 80, timestamp)

    # Summary section
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 120, "Transport Summary")

    c.setFont("Helvetica", 11)
    y = height - 145

    actual_total = dataframe["Allocated Fish"].sum()
    actual_biomass = dataframe["Biomass (kg)"].sum()

    summary_info = [
        f"Selected Tanker: {tanker_name}",
        f"Delivery Type: {delivery_mode_param}",
        f"Allocation Mode: {allocation_mode}",
        f"Total Fish Per Delivery: {actual_total:,}",
        f"Total Biomass Per Delivery: {actual_biomass:,.2f} kg",
        f"Total Tank Volume: {sum(tanks_dict.values()):,} L",
        f"Average Density: {(actual_biomass / (sum(tanks_dict.values()) / 1000)):.2f} kg/m³"
    ]

    if delivery_mode_param == "Multi-day deliveries":
        summary_info.insert(3, f"Number of Deliveries: {num_deliveries_param}")
        if total_fish_all_param:
            summary_info.insert(4, f"Total Fish (All Deliveries): {total_fish_all_param:,}")

    if use_boat_capacity_param and boat_max_volume_param:
        summary_info.insert(1, f"Boat Capacity Limit: {num_boat_tanks_param} × {boat_tank_size_param:,}L = {boat_max_volume_param:,}L")

    for info in summary_info:
        c.drawString(70, y, info)
        y -= 20

    # Tank allocations header
    y -= 30
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Tank Allocations")

    # Table data
    y -= 30
    c.setFont("Helvetica", 10)

    # Column headers
    headers_y = y
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60, headers_y, "Tank")
    c.drawString(130, headers_y, "Volume (L)")
    c.drawString(210, headers_y, "Fish Wt (g)")
    c.drawString(290, headers_y, "Fish Count")
    c.drawString(370, headers_y, "Biomass (kg)")
    c.drawString(460, headers_y, "Density")

    # Draw line under headers
    c.line(50, headers_y - 5, width - 50, headers_y - 5)

    # Data rows
    c.setFont("Helvetica", 9)
    y = headers_y - 25

    for _, row in dataframe.iterrows():
        c.drawString(60, y, str(row['Tank']))
        c.drawString(130, y, f"{row['Volume (L)']:,}")
        c.drawString(210, y, f"{row['Fish Weight (g)']:.1f}")
        c.drawString(290, y, f"{row['Allocated Fish']:,}")
        c.drawString(370, y, f"{row['Biomass (kg)']:.2f}")
        c.drawString(460, y, f"{row['Density (kg/m³)']:.2f}")
        y -= 20

        # Check if we need a new page
        if y < 100:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 9)

    # Add variance section if available
    if variance_dataframe is not None and len(variance_dataframe) > 0:
        # Check if we need a new page
        if y < 300:
            c.showPage()
            y = height - 60

        y -= 30
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "Actual vs Target Variance")

        y -= 30
        c.setFont("Helvetica-Bold", 9)
        c.drawString(60, y, "Tank")
        c.drawString(130, y, "Target")
        c.drawString(200, y, "Actual")
        c.drawString(270, y, "Variance")
        c.drawString(340, y, "Variance %")
        c.drawString(420, y, "Status")

        c.line(50, y - 5, width - 50, y - 5)

        c.setFont("Helvetica", 9)
        y -= 25

        for _, row in variance_dataframe.iterrows():
            c.drawString(60, y, str(row['Tank']))
            c.drawString(130, y, f"{row['Target Fish']:,}")
            c.drawString(200, y, f"{row['Actual Fish']:,}")
            c.drawString(270, y, f"{row['Variance']:+,}")
            c.drawString(340, y, f"{row['Variance %']:+.1f}%")
            c.drawString(420, y, str(row['Status']))
            y -= 20

            if y < 100:
                c.showPage()
                y = height - 60
                c.setFont("Helvetica", 9)

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 30, "Generated by Fish Transport Allocation Tool")

    c.save()
    buffer.seek(0)
    return buffer

# ----- Export Buttons -----
st.subheader("💾 Export Options")

export_col1, export_col2 = st.columns(2)

with export_col1:
    # CSV Export
    csv = df.to_csv(index=False)
    st.download_button(
        label="📄 Download CSV",
        data=csv,
        file_name=f"fish_transport_allocation_{selected_tanker.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )

with export_col2:
    # PDF Export
    pdf_buffer = create_pdf(
        df, selected_tanker, tanks, fish_weights, total_fish, allocation_mode,
        delivery_mode_param=delivery_mode,
        num_deliveries_param=num_deliveries,
        total_fish_all_param=total_fish_all if delivery_mode == "Multi-day deliveries" else None,
        use_boat_capacity_param=use_boat_capacity,
        boat_max_volume_param=boat_max_volume,
        num_boat_tanks_param=num_boat_tanks if use_boat_capacity else None,
        boat_tank_size_param=boat_tank_size if use_boat_capacity else None,
        variance_dataframe=variance_df if record_actual and variance_data else None
    )
    st.download_button(
        label="📑 Download PDF Report",
        data=pdf_buffer,
        file_name=f"fish_transport_report_{selected_tanker.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf"
    )

# ----- Additional Information -----
with st.expander("ℹ️ About This Tool"):
    st.write("""
    ### How It Works

    This tool distributes fish across multiple transport tanks with flexible options:

    #### Tanker Selection
    - **Mackenzies**: 4 tanks (4700L, 5400L, 5900L, 8200L)
    - **Sanford**: 5 tanks (3000L × 4, 7000L × 1)

    #### Boat Capacity Limit
    - **Optional constraint**: Limit tanker load to match destination boat's receiving capacity
    - **Use case**: When the receiving boat has smaller tanks than the tanker (e.g., 3 tanks × 6000L = 18,000L)
    - **How it works**:
      - Specify number of boat tanks and their size
      - System automatically limits which tanker tanks are filled
      - Only fills tanker tanks up to the boat's total capacity
      - Prevents overfilling beyond what the boat can receive
    - **Example**: For Sanford tanker (19,000L total) delivering to boat with 18,000L capacity:
      - Only fills Tanks 1-5 to total 18,000L
      - Prevents wasting fish that can't be unloaded

    #### Delivery Types
    - **Single delivery**: Plan one-time fish transport
    - **Multi-day deliveries**: Plan deliveries over multiple days (e.g., 110k fish over 3 days)
      - Automatically calculates fish per delivery
      - Shows breakdown for each day
      - Ideal for large orders requiring multiple trips

    #### Fish Weight Options
    - **Same weight**: All tanks contain fish of the same size
    - **Different weights**: Each tank can have different sized fish (e.g., 40g fish in tanks 1-2, 30g fish in tanks 3-4)

    #### Allocation Strategies
    - **Equal density**: Fish are distributed to achieve equal kg/m³ across all tanks (accounting for different fish weights)
    - **Manual allocation**: Specify exact fish counts per tank for custom loading
    - **Plan by destination tank requirements**:
      - Step 1: Specify how many fish each destination tank needs (e.g., Destination Tank 3 needs 21,000 fish)
      - Step 2: Map which transport tanks empty into each destination (e.g., Transport Tanks 1 & 3 → Destination Tank 3)
      - Step 3: View calculated loading plan with offloading instructions
      - Perfect for deliveries where specific transport tanks must be combined into specific destination tanks

    ### Density Guidelines

    - **Green (OK)**: Density below warning threshold
    - **Yellow (Warning)**: Density approaching high levels
    - **Red (Critical)**: Density exceeds recommended safe limits

    ### Features

    - ✅ Two tanker configurations (Mackenzies & Sanford)
    - ✅ Boat capacity constraint (limit load by destination boat tanks)
    - ✅ Single or multi-day delivery planning
    - ✅ Destination tank requirement planning
    - ✅ Per-tank fish weight customization
    - ✅ Equal density or manual allocation
    - ✅ Real-time density monitoring
    - ✅ Visual charts and graphs
    - ✅ Export to CSV and PDF
    - ✅ Adjustable safety thresholds
    """)

# Footer
st.divider()
st.caption(f"🐟 Fish Transport Allocation Tool | {selected_tanker} | Optimizing transport density for fish welfare")
