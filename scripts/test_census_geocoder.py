"""
Test U.S. Census Bureau Geocoder API: lat/lng -> county, state.
Uses test data: 1 Infinite Loop, Cupertino, CA 95014 -> lat=37.3331, lng=-122.02889.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.census_geocoder import lat_lng_to_geography

def main():
    lat = 37.3331
    lon = -122.02889
    print(f"Test: lat={lat}, lon={lon} (1 Infinite Loop, Cupertino, CA 95014)\n")
    geo = lat_lng_to_geography(lat, lon)
    if geo:
        print(f"\nResult: state_fips={geo.state_fips}, state_abbreviation={geo.state_abbreviation}, county_name={geo.county_name}, county_fips={geo.county_fips}")
    else:
        print("\nResult: None (lookup failed)")

if __name__ == "__main__":
    main()
