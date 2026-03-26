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
import json

# ----- Configuration -----
DEFAULT_TANKER_CONFIGS = {
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
    },
    "Move Logistics (Tanker 3)": {
        "Tank 1": 2878,
        "Tank 2": 4197,
        "Tank 3": 4758,
        "Tank 4": 6959,
        "Tank 5": 4387
    }
}

# Recommended density ranges (kg/m³)
DENSITY_WARNING_THRESHOLD = 80
DENSITY_CRITICAL_THRESHOLD = 100

st.set_page_config(page_title="Fish Transport Allocation", layout="wide")
st.title("🐟 Fish Transport Allocation Tool")

# Initialize session state for custom tankers
if 'custom_tankers' not in st.session_state:
    st.session_state.custom_tankers = {}

# Combine default and custom tankers
TANKER_CONFIGS = {**DEFAULT_TANKER_CONFIGS, **st.session_state.custom_tankers}

# ----- Sidebar for Settings -----
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Transport mode selection
    st.subheader("🚛 Transport Mode")
    transport_mode = st.radio(
        "Select mode",
        options=["Single Truck", "Multi-Truck (Equal Density)"],
        index=0,
        help="Single truck: allocate fish to one tanker. Multi-truck: split load across multiple tankers for equal density."
    )
    
    st.divider()
    
    # ----- Create New Tanker Section -----
    st.subheader("➕ Create New Tanker")
    with st.expander("Add a custom tanker", expanded=False):
        new_tanker_name = st.text_input("Tanker name", placeholder="e.g., Company X Truck 2")
        
        num_new_tanks = st.number_input("Number of tanks", min_value=1, max_value=10, value=4, step=1)
        
        new_tank_volumes = {}
        for i in range(int(num_new_tanks)):
            vol = st.number_input(f"Tank {i+1} volume (L)", min_value=100, value=3000, step=100, key=f"new_tank_{i}")
            new_tank_volumes[f"Tank {i+1}"] = vol
        
        if st.button("💾 Save Tanker"):
            if new_tanker_name and new_tanker_name.strip():
                st.session_state.custom_tankers[new_tanker_name.strip()] = new_tank_volumes
                st.success(f"✅ Added '{new_tanker_name}' with {len(new_tank_volumes)} tanks ({sum(new_tank_volumes.values()):,}L total)")
                st.rerun()
            else:
                st.error("Please enter a tanker name")
        
        # Option to delete custom tankers
        if st.session_state.custom_tankers:
            st.divider()
            st.write("**Manage custom tankers:**")
            tanker_to_delete = st.selectbox("Select tanker to delete", options=list(st.session_state.custom_tankers.keys()))
            if st.button("🗑️ Delete Selected Tanker"):
                del st.session_state.custom_tankers[tanker_to_delete]
                st.success(f"Deleted '{tanker_to_delete}'")
                st.rerun()
    
    st.divider()
    
    # Refresh tanker configs after potential additions
    TANKER_CONFIGS = {**DEFAULT_TANKER_CONFIGS, **st.session_state.custom_tankers}
    
    # ----- Single Truck Mode -----
    if transport_mode == "Single Truck":
        st.subheader("🚛 Tanker Selection")
        selected_tanker = st.selectbox(
            "Select tanker",
            options=list(TANKER_CONFIGS.keys()),
            index=0
        )
        
        # Display tanker info
        tanker_total = sum(TANKER_CONFIGS[selected_tanker].values())
        st.info(f"**{selected_tanker}** ({tanker_total:,}L)\n\n" + 
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
        
        selected_tankers = [selected_tanker]  # For compatibility with rest of code
        multi_truck_tanks = {selected_tanker: tanks}
    
    # ----- Multi-Truck Mode -----
    else:
        st.subheader("🚛 Select Tankers")
        selected_tankers = st.multiselect(
            "Choose tankers to use",
            options=list(TANKER_CONFIGS.keys()),
            default=list(TANKER_CONFIGS.keys())[:2] if len(TANKER_CONFIGS) >= 2 else list(TANKER_CONFIGS.keys())
        )
        
        if selected_tankers:
            # Display combined capacity
            multi_truck_tanks = {}
            total_combined_volume = 0
            
            st.write("**Selected tankers:**")
            for tanker in selected_tankers:
                tanker_vol = sum(TANKER_CONFIGS[tanker].values())
                total_combined_volume += tanker_vol
                multi_truck_tanks[tanker] = TANKER_CONFIGS[tanker].copy()
                st.write(f"- {tanker}: {tanker_vol:,}L")
            
            st.success(f"**Combined capacity: {total_combined_volume:,}L**")
        else:
            st.warning("Please select at least one tanker")
            multi_truck_tanks = {}
        
        # For single-truck compatibility
        tanks = {}
        if selected_tankers:
            selected_tanker = selected_tankers[0]
            for tanker in selected_tankers:
                for tank_name, vol in TANKER_CONFIGS[tanker].items():
                    tanks[f"{tanker} - {tank_name}"] = vol
    
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
st.subheader("🐠 Fish Configuration")

col_fish1, col_fish2 = st.columns(2)

with col_fish1:
    total_fish = st.number_input("Total number of fish to transport", min_value=1, value=30000, step=100)

with col_fish2:
    fish_weight = st.number_input("Average fish weight (grams)", min_value=1.0, value=60.0, step=5.0)

# Calculate totals
total_biomass_kg = total_fish * fish_weight / 1000

st.info(f"📊 **Total biomass:** {total_biomass_kg:,.2f} kg ({total_fish:,} fish × {fish_weight}g)")

st.divider()

# ----- Multi-Truck Allocation -----
if transport_mode == "Multi-Truck (Equal Density)" and selected_tankers and len(selected_tankers) > 1:
    st.subheader("🚛 Multi-Truck Equal Density Allocation")
    
    # Calculate total volume across all selected tankers
    total_combined_volume = sum(sum(TANKER_CONFIGS[t].values()) for t in selected_tankers)
    
    # Target density (equal across all)
    target_density = total_biomass_kg / (total_combined_volume / 1000)
    
    st.write(f"**Target density across all trucks:** {target_density:.2f} kg/m³")
    
    # Check density status
    if target_density >= critical_threshold:
        st.error(f"🔴 **Critical:** Target density ({target_density:.2f} kg/m³) exceeds critical threshold ({critical_threshold} kg/m³)")
    elif target_density >= warning_threshold:
        st.warning(f"🟡 **Warning:** Target density ({target_density:.2f} kg/m³) exceeds warning threshold ({warning_threshold} kg/m³)")
    else:
        st.success(f"🟢 **Good:** Target density ({target_density:.2f} kg/m³) is within safe limits")
    
    st.divider()
    
    # Calculate allocation per truck and per tank
    multi_truck_allocations = []
    all_tank_allocations = []
    
    for tanker in selected_tankers:
        tanker_volume = sum(TANKER_CONFIGS[tanker].values())
        tanker_volume_m3 = tanker_volume / 1000
        
        # Allocate fish proportionally by volume
        fish_for_tanker = round(total_fish * (tanker_volume / total_combined_volume))
        biomass_for_tanker = fish_for_tanker * fish_weight / 1000
        tanker_density = biomass_for_tanker / tanker_volume_m3
        
        # Determine status
        if tanker_density >= critical_threshold:
            status = "🔴 Critical"
        elif tanker_density >= warning_threshold:
            status = "🟡 Warning"
        else:
            status = "🟢 OK"
        
        multi_truck_allocations.append({
            "Tanker": tanker,
            "Volume (L)": tanker_volume,
            "Allocated Fish": fish_for_tanker,
            "Biomass (kg)": round(biomass_for_tanker, 2),
            "Density (kg/m³)": round(tanker_density, 2),
            "Status": status
        })
        
        # Now allocate within this tanker's tanks (equal density within tanker)
        tanker_tanks = TANKER_CONFIGS[tanker]
        for tank_name, tank_vol in tanker_tanks.items():
            fish_for_tank = round(fish_for_tanker * (tank_vol / tanker_volume))
            tank_biomass = fish_for_tank * fish_weight / 1000
            tank_density = tank_biomass / (tank_vol / 1000)
            
            if tank_density >= critical_threshold:
                tank_status = "🔴 Critical"
            elif tank_density >= warning_threshold:
                tank_status = "🟡 Warning"
            else:
                tank_status = "🟢 OK"
            
            all_tank_allocations.append({
                "Tanker": tanker,
                "Tank": tank_name,
                "Volume (L)": tank_vol,
                "Fish Weight (g)": fish_weight,
                "Allocated Fish": fish_for_tank,
                "Biomass (kg)": round(tank_biomass, 2),
                "Density (kg/m³)": round(tank_density, 2),
                "Status": tank_status
            })
    
    # Display truck-level summary
    st.subheader("📊 Truck-Level Allocation")
    truck_df = pd.DataFrame(multi_truck_allocations)
    st.dataframe(truck_df, use_container_width=True, hide_index=True)
    
    # Visualize truck allocation
    fig_trucks = px.bar(truck_df, x="Tanker", y="Allocated Fish",
                        title="Fish Allocation by Truck",
                        color="Density (kg/m³)",
                        color_continuous_scale="RdYlGn_r",
                        text="Allocated Fish",
                        hover_data=["Volume (L)", "Biomass (kg)"])
    fig_trucks.update_traces(texttemplate='%{text:,}', textposition='outside')
    st.plotly_chart(fig_trucks, use_container_width=True)
    
    st.divider()
    
    # Display tank-level detail
    st.subheader("📋 Tank-Level Allocation (All Trucks)")
    tank_df = pd.DataFrame(all_tank_allocations)
    
    # Add percentage column
    total_allocated = tank_df["Allocated Fish"].sum()
    tank_df["% of Total"] = round((tank_df["Allocated Fish"] / total_allocated) * 100, 1) if total_allocated > 0 else 0
    
    st.dataframe(tank_df, use_container_width=True, hide_index=True)
    
    # Summary metrics
    st.subheader("📊 Summary Statistics")
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    
    with summary_col1:
        st.metric("Total Fish Allocated", f"{total_allocated:,}")
    with summary_col2:
        st.metric("Total Biomass", f"{tank_df['Biomass (kg)'].sum():,.2f} kg")
    with summary_col3:
        st.metric("Average Density", f"{target_density:.2f} kg/m³")
    with summary_col4:
        st.metric("Trucks Used", f"{len(selected_tankers)}")
    
    # Tank-level visualizations
    st.subheader("📈 Visualizations")
    
    viz_col1, viz_col2 = st.columns(2)
    
    with viz_col1:
        # Fish allocation by tank (grouped by truck)
        fig_tanks = px.bar(tank_df, x="Tank", y="Allocated Fish",
                          color="Tanker",
                          title="Fish Allocation by Tank",
                          text="Allocated Fish",
                          barmode="group")
        fig_tanks.update_traces(texttemplate='%{text:,}', textposition='outside')
        st.plotly_chart(fig_tanks, use_container_width=True)
    
    with viz_col2:
        # Density by tank
        fig_density = px.bar(tank_df, x="Tank", y="Density (kg/m³)",
                            color="Tanker",
                            title="Density by Tank (kg/m³)",
                            text="Density (kg/m³)",
                            barmode="group")
        fig_density.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig_density.add_hline(y=warning_threshold, line_dash="dash", line_color="orange",
                             annotation_text="Warning", annotation_position="right")
        fig_density.add_hline(y=critical_threshold, line_dash="dash", line_color="red",
                             annotation_text="Critical", annotation_position="right")
        st.plotly_chart(fig_density, use_container_width=True)
    
    # Pie chart showing distribution by truck
    fig_pie = px.pie(truck_df, values="Allocated Fish", names="Tanker",
                     title="Fish Distribution by Truck",
                     hole=0.3)
    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
    st.plotly_chart(fig_pie, use_container_width=True)
    
    # Set df for export functions
    df = tank_df
    allocations = all_tank_allocations

# ----- Single Truck Mode (Original Logic) -----
else:
    if transport_mode == "Single Truck" or (transport_mode == "Multi-Truck (Equal Density)" and len(selected_tankers) <= 1):
        
        if transport_mode == "Multi-Truck (Equal Density)" and len(selected_tankers) == 1:
            st.info("ℹ️ Only one truck selected — using single truck mode")
        
        st.write("This tool distributes fish across tanks based on tank volume to achieve equal or custom density (kg/m³).")
        
        # Fish weight mode for single truck
        st.subheader("🐠 Fish Weight Configuration")
        
        weight_mode = st.radio(
            "Fish weight mode",
            options=["Same weight for all tanks", "Different weights per tank"],
            horizontal=True
        )
        
        fish_weights = {}
        if weight_mode == "Same weight for all tanks":
            for tank_name in tanks.keys():
                fish_weights[tank_name] = fish_weight
        else:
            st.write("**Set fish weight for each tank:**")
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
                                value=fish_weight,
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
            num_deliveries = 1
            fish_per_delivery = total_fish
        else:  # Multi-day deliveries
            col1, col2 = st.columns(2)
            with col1:
                total_fish_all = st.number_input("Total fish to deliver (all days)", min_value=1, value=110000, step=1000)
            with col2:
                num_deliveries = st.number_input("Number of deliveries", min_value=2, max_value=10, value=3, step=1)
            
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
                                value=21000 if i + j in [2, 3] else 0,
                                step=100,
                                key=f"dest_{tank_name}"
                            )
            
            st.divider()
            
            # Map transport tanks to destination tanks
            st.write("**Step 2: Map transport tanks to destination tanks**")
            st.caption("Specify which transport tanks will be emptied into each destination tank")
            
            transport_to_dest_mapping = {}
            tank_list = list(tanks.keys())
            
            active_dest_tanks = [k for k, v in destination_requirements.items() if v > 0]
            
            for dest_tank in active_dest_tanks:
                st.write(f"**{dest_tank}** (needs {destination_requirements[dest_tank]:,} fish)")
                
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
                
                calculated_allocations = {tank: 0 for tank in tank_list}
                
                for dest_tank, transport_tanks in transport_to_dest_mapping.items():
                    fish_needed = destination_requirements[dest_tank]
                    num_transport_tanks = len(transport_tanks)
                    
                    if num_transport_tanks > 0:
                        total_assigned_volume = sum(tanks[t] for t in transport_tanks)
                        
                        for transport_tank in transport_tanks:
                            tank_volume = tanks[transport_tank]
                            fish_for_this_tank = round(fish_needed * (tank_volume / total_assigned_volume))
                            calculated_allocations[transport_tank] += fish_for_this_tank
                
                allocation_plan_data = []
                for tank_name, fish_count in calculated_allocations.items():
                    if fish_count > 0:
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
            cumulative_volume = 0
            tanks_to_use = {}
            
            for tank_name, vol in tanks.items():
                if cumulative_volume + vol <= boat_max_volume:
                    tanks_to_use[tank_name] = vol
                    cumulative_volume += vol
                elif cumulative_volume < boat_max_volume:
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
        
        if allocation_mode == "Plan by destination tank requirements" and 'calculated_allocations' in locals() and calculated_allocations:
            for tank_name, vol in effective_tanks.items():
                fish_for_tank = calculated_allocations.get(tank_name, 0)
                biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
                density_kg_m3 = biomass_kg / (vol / 1000) if vol > 0 else 0
                
                if density_kg_m3 >= critical_threshold:
                    status = "🔴 Critical"
                    density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Critical)")
                elif density_kg_m3 >= warning_threshold:
                    status = "🟡 Warning"
                    density_alerts.append(f"{tank_name}: {density_kg_m3:.2f} kg/m³ (Warning)")
                else:
                    status = "🟢 OK"
                
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
            weight_volume_ratios = {tank: effective_tanks[tank] / fish_weights[tank] for tank in effective_tanks.keys()}
            total_ratio = sum(weight_volume_ratios.values())
            
            for tank_name, vol in effective_tanks.items():
                fish_for_tank = round(total_fish * (weight_volume_ratios[tank_name] / total_ratio))
                biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
                density_kg_m3 = biomass_kg / (vol / 1000)
                
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
            cols_per_row = 3
            
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
            
            for tank_name, vol in effective_tanks.items():
                fish_for_tank = manual_allocations[tank_name]
                biomass_kg = fish_for_tank * fish_weights[tank_name] / 1000
                density_kg_m3 = biomass_kg / (vol / 1000) if vol > 0 else 0
                
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
            
            manual_total = sum(manual_allocations.values())
            if manual_total != total_fish:
                st.warning(f"⚠️ Manual allocation total ({manual_total:,}) doesn't match target ({total_fish:,}). Difference: {manual_total - total_fish:+,}")
        
        df = pd.DataFrame(allocations)
        
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
        
        # ----- Allocation Table -----
        st.subheader("📋 Transport Tank Allocation")
        
        if use_boat_capacity and boat_max_volume:
            tanks_used = list(effective_tanks.keys())
            tanks_excluded = [t for t in tanks.keys() if t not in effective_tanks]
            info_parts = [f"🚢 **Boat Capacity Mode:** Loading {effective_volume:,}L of {total_volume:,}L tanker capacity"]
            info_parts.append(f"**Tanks in use:** {', '.join(tanks_used)}")
            if tanks_excluded:
                info_parts.append(f"**Tanks excluded:** {', '.join(tanks_excluded)} (exceed boat capacity)")
            st.info(" | ".join(info_parts))
        
        df["% of Total"] = round((df["Allocated Fish"] / actual_total_fish) * 100, 1) if actual_total_fish > 0 else 0
        
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # ----- Visualizations -----
        st.subheader("📈 Visualizations")
        
        viz_col1, viz_col2 = st.columns(2)
        
        with viz_col1:
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
        
        viz_col3, viz_col4 = st.columns(2)
        
        with viz_col3:
            fig_pie = px.pie(df, values="Allocated Fish", names="Tank",
                            title="Fish Distribution Percentage",
                            hole=0.3)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with viz_col4:
            fig_weight = px.bar(df, x="Tank", y="Fish Weight (g)",
                               title="Fish Weight by Tank",
                               text="Fish Weight (g)",
                               color="Fish Weight (g)",
                               color_continuous_scale="Blues")
            fig_weight.update_traces(texttemplate='%{text:.1f}g', textposition='outside')
            fig_weight.update_layout(showlegend=False)
            st.plotly_chart(fig_weight, use_container_width=True)


# ----- Export Functions -----
st.divider()
st.subheader("💾 Export Options")

def create_csv_export(dataframe):
    return dataframe.to_csv(index=False)

export_col1, export_col2 = st.columns(2)

with export_col1:
    csv = df.to_csv(index=False)
    tanker_name_for_file = selected_tankers[0] if len(selected_tankers) == 1 else "multi_truck"
    st.download_button(
        label="📄 Download CSV",
        data=csv,
        file_name=f"fish_transport_allocation_{tanker_name_for_file.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv"
    )

with export_col2:
    # Summary text export
    summary_text = f"""Fish Transport Allocation Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Transport Mode: {transport_mode}
{"Tankers: " + ", ".join(selected_tankers) if transport_mode == "Multi-Truck (Equal Density)" else "Tanker: " + selected_tanker}
Total Fish: {total_fish:,}
Average Fish Weight: {fish_weight}g
Total Biomass: {total_fish * fish_weight / 1000:,.2f} kg

Tank Allocations:
"""
    for _, row in df.iterrows():
        if 'Tanker' in df.columns:
            summary_text += f"  {row['Tanker']} - {row['Tank']}: {row['Allocated Fish']:,} fish, {row['Density (kg/m³)']:.2f} kg/m³\n"
        else:
            summary_text += f"  {row['Tank']}: {row['Allocated Fish']:,} fish, {row['Density (kg/m³)']:.2f} kg/m³\n"
    
    st.download_button(
        label="📝 Download Summary (TXT)",
        data=summary_text,
        file_name=f"fish_transport_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
        mime="text/plain"
    )


# ----- Additional Information -----
with st.expander("ℹ️ About This Tool"):
    st.write("""
    ### How It Works
    
    **Single Truck Mode:**
    - Select a tanker from the dropdown
    - Enter total fish count and average weight
    - Choose allocation strategy (equal density, manual, or destination-based)
    - View density calculations and alerts
    
    **Multi-Truck Mode (Equal Density):**
    - Select multiple tankers
    - Enter total fish count and average weight
    - Fish are automatically distributed across all trucks to achieve equal density
    - Each truck's tanks are also balanced for equal density
    
    **Create New Tanker:**
    - Use the sidebar to add custom tankers with your own tank configurations
    - Custom tankers are saved for the session
    
    ### Density Guidelines
    - 🟢 **OK:** Below warning threshold (default: 80 kg/m³)
    - 🟡 **Warning:** Between warning and critical thresholds
    - 🔴 **Critical:** Above critical threshold (default: 100 kg/m³)
    
    ### Available Tankers
    """)
    
    for tanker_name, tanker_tanks in TANKER_CONFIGS.items():
        total_vol = sum(tanker_tanks.values())
        st.write(f"**{tanker_name}** ({total_vol:,}L total)")
        for tank, vol in tanker_tanks.items():
            st.write(f"  - {tank}: {vol:,}L")
