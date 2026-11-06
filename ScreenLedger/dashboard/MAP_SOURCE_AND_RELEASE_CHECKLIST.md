# Official India geometry — release checklist

## Verified sources

The National Water Data Portal (Government of India, National Water Informatics Centre) lists **State Boundary** GeoJSON / KML / SHP with **Survey of India** as data producer. Its state-boundary resource is called `state_NWIC_GeoJSON.zip`. The public dataset page indicated a dataset update date of October 1, 2026; the resource page lists May 1, 2025 as the resource update date. These dates are metadata, not proof of the geometry's edition or accuracy.

The Survey of India publishes the 2026 political map of India (English 13th edition). This is the designated reference for visual checking of India's external boundary and the separate Jammu & Kashmir and Ladakh union territories, not an interchangeable polygon dataset.

## Before marking production ready

- [ ] Download the ZIP from the exact `nwdp.nwic.gov.in` link in the README.
- [ ] Record archive SHA-256, ZIP internal filename, downloaded timestamp and resource metadata.
- [ ] Check 28 states + 8 union territories; do not accept 2019-era combined J&K/Ladakh geometry.
- [ ] Confirm that the internal name keys and coordinates are valid and properly reprojected where necessary.
- [ ] Inspect **full Jammu & Kashmir and Ladakh shapes** (including northern/western extent) against the Survey of India 2026 political map.
- [ ] Verify national outline, Northeast, coastline and small islands; compare against SoI references at appropriate scale.
- [ ] Verify official boundaries are usable/licensed for the intended commercial deployment; provide visible attribution.
- [ ] Verify map pointer, keyboard and touch interaction on desktop/mobile with actual official polygons.
- [ ] If district-level maps are required, acquire separately verified official district GeoJSON; do not substitute state polygons.
- [ ] Only then change the UI's geographic data status from **Pending review** to **Verified**.

## Link and metadata

- Dataset: https://nwdp.nwic.gov.in/dataset/state-boundary
- Resource: https://nwdp.nwic.gov.in/dataset/state-boundary/resource/f039e721-132c-4a24-9e5e-07af03064b4d
- Government ZIP: https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_nwic_geojson.zip
- Political map: https://surveyofindia.gov.in/pages/political-map-of-india
- Portal copyright: https://nwdp.nwic.gov.in/footer/copyrightPolicy
- SoI outline vector notice: https://surveyofindia.gov.in/documents/ibd-vectorformat.pdf

## Implementation notes

The importer intentionally fails if any state or UT is missing, if essential polygon geometry is invalid or if the north-region features appear truncated. If the official file schema differs from the recognized property names, inspect the error message and adapt the property key, **never hardcode replacement polygons**. Automatic checks alone do not determine contested boundary correctness.

Aggregation should remain screening based and deduplicated by session ID across overlapping city feeds. A single city feed is not whole-state coverage. The occupancy percentage uses unavailable seats divided by total capacity and should not be labeled verified paid attendance. The hourly delta must compare two genuinely comparable snapshots and be null when no earlier capture exists.
