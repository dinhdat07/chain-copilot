import pandas as pd
import numpy as np
import random
import os

random.seed(42)
np.random.seed(42)

# 1. Update warehouses
warehouses = pd.DataFrame([
    {"warehouse_id": "WH_HN", "name": "Hanoi Hub", "capacity": 5000, "region": "north"},
    {"warehouse_id": "WH_DN", "name": "Da Nang Hub", "capacity": 3000, "region": "central"},
    {"warehouse_id": "WH_HCM", "name": "Ho Chi Minh Hub", "capacity": 6000, "region": "south"}
])
warehouses.to_csv("data/warehouses.csv", index=False)

# 2. Update routes
routes = pd.DataFrame([
    {"route_id": "R_BN_HN_MAIN", "origin": "Bac Ninh", "destination": "Hanoi", "transit_days": 1, "cost": 50.0, "risk_score": 0.1, "status": "active"},
    {"route_id": "R_BN_HN_ALT", "origin": "Bac Ninh", "destination": "Hanoi", "transit_days": 2, "cost": 75.0, "risk_score": 0.2, "status": "active"},
    {"route_id": "R_HP_HN_MAIN", "origin": "Hai Phong", "destination": "Hanoi", "transit_days": 1, "cost": 80.0, "risk_score": 0.15, "status": "active"},
    {"route_id": "R_HP_HN_ALT", "origin": "Hai Phong", "destination": "Hanoi", "transit_days": 2, "cost": 110.0, "risk_score": 0.25, "status": "active"},
    {"route_id": "R_QN_DN_MAIN", "origin": "Quang Nam", "destination": "Da Nang", "transit_days": 1, "cost": 40.0, "risk_score": 0.1, "status": "active"},
    {"route_id": "R_QN_DN_ALT", "origin": "Quang Nam", "destination": "Da Nang", "transit_days": 2, "cost": 60.0, "risk_score": 0.2, "status": "active"},
    {"route_id": "R_BD_HCM_MAIN", "origin": "Binh Duong", "destination": "HCMC", "transit_days": 1, "cost": 45.0, "risk_score": 0.1, "status": "active"},
    {"route_id": "R_BD_HCM_ALT", "origin": "Binh Duong", "destination": "HCMC", "transit_days": 2, "cost": 65.0, "risk_score": 0.2, "status": "active"},
    {"route_id": "R_DNAI_HCM_MAIN", "origin": "Dong Nai", "destination": "HCMC", "transit_days": 1, "cost": 55.0, "risk_score": 0.15, "status": "active"},
    {"route_id": "R_DNAI_HCM_ALT", "origin": "Dong Nai", "destination": "HCMC", "transit_days": 2, "cost": 85.0, "risk_score": 0.25, "status": "active"},
])
routes.to_csv("data/routes.csv", index=False)

# Read existing inventory to get SKUs
inv_df = pd.read_csv("data/inventory.csv")
skus = inv_df["sku"].tolist()

# Assign each SKU to a warehouse
sku_warehouse = {}
for i, sku in enumerate(skus):
    if i % 3 == 0:
        sku_warehouse[sku] = "WH_HN"
    elif i % 3 == 1:
        sku_warehouse[sku] = "WH_DN"
    else:
        sku_warehouse[sku] = "WH_HCM"

warehouse_suppliers = {
    "WH_HN": ["SUP_BN", "SUP_HP"],
    "WH_DN": ["SUP_QN"],
    "WH_HCM": ["SUP_BD", "SUP_DNAI"]
}

supplier_routes = {
    "SUP_BN": "R_BN_HN_MAIN",
    "SUP_HP": "R_HP_HN_MAIN",
    "SUP_QN": "R_QN_DN_MAIN",
    "SUP_BD": "R_BD_HCM_MAIN",
    "SUP_DNAI": "R_DNAI_HCM_MAIN"
}

# 3. Create Suppliers
new_suppliers = []
for sku in skus:
    wh = sku_warehouse[sku]
    sups = warehouse_suppliers[wh]
    primary_sup = sups[0]
    
    # Primary
    new_suppliers.append({
        "supplier_id": primary_sup,
        "sku": sku,
        "unit_cost": round(random.uniform(50, 500), 2),
        "lead_time_days": random.randint(1, 3),
        "reliability": round(random.uniform(0.85, 0.98), 2),
        "is_primary": True,
        "status": "active"
    })
    
    # Secondary (if available)
    if len(sups) > 1:
        sec_sup = sups[1]
        new_suppliers.append({
            "supplier_id": sec_sup,
            "sku": sku,
            "unit_cost": round(random.uniform(50, 500), 2),
            "lead_time_days": random.randint(2, 5),
            "reliability": round(random.uniform(0.70, 0.90), 2),
            "is_primary": False,
            "status": "active"
        })

pd.DataFrame(new_suppliers).to_csv("data/suppliers.csv", index=False)

# 4. Update Inventory
for i, row in inv_df.iterrows():
    sku = row["sku"]
    wh = sku_warehouse[sku]
    pref_sup = warehouse_suppliers[wh][0]
    pref_route = supplier_routes[pref_sup]
    
    inv_df.at[i, "warehouse_id"] = wh
    inv_df.at[i, "preferred_supplier_id"] = pref_sup
    inv_df.at[i, "preferred_route_id"] = pref_route

inv_df.to_csv("data/inventory.csv", index=False)

# 5. Update Orders
orders_df = pd.read_csv("data/orders.csv")
for i, row in orders_df.iterrows():
    sku = row["sku"]
    if sku in sku_warehouse:
        orders_df.at[i, "warehouse_id"] = sku_warehouse[sku]
orders_df.to_csv("data/orders.csv", index=False)

