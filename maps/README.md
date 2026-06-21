# Map Assets

Create a traceable map after the mapping session:

```bash
ros2 run smart_car_decision map_asset save lab-20260621 \
  --site engineering-lab \
  --bag-path bags/lab-20260621
```

The command refuses to overwrite an existing map ID. Each directory contains
`map.yaml`, `map.pgm`, `metadata.json`, and `notes.md`.

Inspect a saved map:

```bash
ros2 run smart_car_decision map_asset inspect maps/lab-20260621/map.yaml
```

Reload it without starting localization:

```bash
ros2 launch smart_car_decision map_view.launch.py \
  map:=$PWD/maps/lab-20260621/map.yaml
```

`preview.png`, reload verification, second-run comparison, and measured field
dimensions are Jetson field-test artifacts and must be added before acceptance.
