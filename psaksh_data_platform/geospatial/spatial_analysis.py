"""
Geospatial analysis — catchment areas, facility coverage, and household mapping.

Requires: geopandas, shapely, folium
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from loguru import logger


# ---------------------------------------------------------------------------
# Convert household GPS to GeoDataFrame
# ---------------------------------------------------------------------------

def households_to_geodataframe(households: pd.DataFrame) -> gpd.GeoDataFrame:
    """
    Convert household DataFrame with GPS columns to a GeoDataFrame (WGS84).
    Drops rows with missing GPS.
    """
    df = households.dropna(subset=["gps_latitude", "gps_longitude"]).copy()
    geometry = [Point(lon, lat) for lon, lat in zip(df["gps_longitude"], df["gps_latitude"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    logger.info(f"  Households GeoDataFrame: {len(gdf):,} points (WGS84)")
    return gdf


def facilities_to_geodataframe(facilities: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert facility DataFrame to GeoDataFrame."""
    df = facilities.dropna(subset=["gps_latitude", "gps_longitude"]).copy()
    geometry = [Point(lon, lat) for lon, lat in zip(df["gps_longitude"], df["gps_latitude"])]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# Catchment analysis
# ---------------------------------------------------------------------------

def assign_catchment(
    households_gdf: gpd.GeoDataFrame,
    facilities_gdf: gpd.GeoDataFrame,
    radius_km: float = 5.0,
) -> gpd.GeoDataFrame:
    """
    Assign each household to the nearest facility within radius_km.
    Uses projected CRS (UTM zone 43N for Pakistan) for accurate distance calculation.
    """
    # Project to UTM 43N (EPSG:32643) for metric distances
    hh_proj  = households_gdf.to_crs("EPSG:32643")
    fac_proj = facilities_gdf.to_crs("EPSG:32643")

    # Spatial join: nearest facility
    hh_proj["nearest_facility_id"]   = None
    hh_proj["distance_to_nearest_m"] = None

    for idx, hh in hh_proj.iterrows():
        distances = fac_proj.geometry.distance(hh.geometry)
        nearest_idx = distances.idxmin()
        min_dist    = distances.min()
        hh_proj.at[idx, "nearest_facility_id"]   = fac_proj.at[nearest_idx, "facility_id"]
        hh_proj.at[idx, "distance_to_nearest_m"] = round(min_dist, 1)

    hh_proj["within_catchment"] = hh_proj["distance_to_nearest_m"] <= (radius_km * 1000)
    logger.info(
        f"  {hh_proj['within_catchment'].sum():,} / {len(hh_proj):,} households "
        f"within {radius_km}km of a facility"
    )
    return hh_proj.to_crs("EPSG:4326")


# ---------------------------------------------------------------------------
# Folium web map
# ---------------------------------------------------------------------------

def build_coverage_map(
    households_gdf: gpd.GeoDataFrame,
    facilities_gdf: gpd.GeoDataFrame,
    indicator_col: Optional[str] = "stunted",
    output_path: Optional[str | Path] = None,
) -> folium.Map:
    """
    Build an interactive Folium map showing:
      - Household locations coloured by a nutrition indicator
      - Facility locations with type markers
      - 5km catchment circles around facilities

    Args:
        households_gdf: GeoDataFrame of households.
        facilities_gdf: GeoDataFrame of facilities.
        indicator_col:  Column to colour households by (binary 0/1).
        output_path:    If provided, saves the map as an HTML file.

    Returns:
        folium.Map object.
    """
    # Centre map on Pakistan
    centre = [30.5, 72.5]
    m = folium.Map(location=centre, zoom_start=7, tiles="CartoDB positron")

    # Facility markers
    facility_icons = {"DHQ": "hospital-o", "RHC": "medkit", "BHU": "plus-square"}
    facility_colors = {"DHQ": "red", "RHC": "orange", "BHU": "blue"}

    for _, fac in facilities_gdf.iterrows():
        ftype = fac.get("facility_type", "BHU")
        folium.Marker(
            location=[fac.geometry.y, fac.geometry.x],
            popup=folium.Popup(
                f"<b>{fac.get('facility_name', fac.get('facility_id'))}</b><br>"
                f"Type: {ftype}<br>District: {fac.get('district', '')}",
                max_width=200,
            ),
            icon=folium.Icon(color=facility_colors.get(ftype, "gray"), icon="plus-sign"),
        ).add_to(m)

        # 5km catchment circle
        folium.Circle(
            location=[fac.geometry.y, fac.geometry.x],
            radius=5000,
            color=facility_colors.get(ftype, "gray"),
            fill=True,
            fill_opacity=0.05,
            weight=1,
        ).add_to(m)

    # Household dots
    if indicator_col and indicator_col in households_gdf.columns:
        for _, hh in households_gdf.iterrows():
            val = hh.get(indicator_col)
            color = "red" if val == 1 else "green" if val == 0 else "gray"
            folium.CircleMarker(
                location=[hh.geometry.y, hh.geometry.x],
                radius=3,
                color=color,
                fill=True,
                fill_opacity=0.6,
                popup=f"HH: {hh.get('household_id', '')} | {indicator_col}: {val}",
            ).add_to(m)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        m.save(str(output_path))
        logger.info(f"  Map saved → {output_path}")

    return m
