;FLAVOR:RepRap
;TIME:1234
;Filament used: 5.67m
;Layer height: 0.2
;Generated with PrusaSlicer

M107
M190 S60 ; set bed temperature
M104 S190 ; set extruder temperature
M109 S190 ; wait for extruder temperature
G21 ; set units to millimeters
G90 ; use absolute coordinates
M82 ; use absolute distances for extrusion
G92 E0
G1 Z0.2 F1200 ; move to layer height

; Arc Overhang Layer 1
G1 X10 Y10 F3000
G1 E10 F600 ; prime the nozzle
G1 X50 Y10 E20 F1200
G1 X50 Y50 E30
G1 X10 Y50 E40
G1 X10 Y10 E50
G92 E0

; Arc Overhang Layer 2
G1 Z0.4 F1200 ; move to next layer height
G1 X15 Y15 E60 F1200
G1 X45 Y15 E70
G1 X45 Y45 E80
G1 X15 Y45 E90
G1 X15 Y15 E100
G92 E0

; Continue with additional layers...

M104 S0 ; turn off extruder
M140 S0 ; turn off bed
M84 ; disable motors
