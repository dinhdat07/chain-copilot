# Feature Plan: Overhaul Supply Chain Data

- Reorganized warehouses to 3 regional hubs: North (WH_HN), Central (WH_DN), South (WH_HCM).
- Reorganized suppliers to 5 regional entities: Bac Ninh, Hai Phong (North); Quang Nam (Central); Binh Duong, Dong Nai (South).
- Updated routes to connect regions (10 routes: 1 Main + 1 Alt per supplier-warehouse connection).
- Redistributed 51 SKUs into respective regional warehouses, with preferred supplier/route dynamically assigned.
- Patched mock APIs (`routers.py`) for Weather, Routes, and Suppliers to align geographically and id-wise.
