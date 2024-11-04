"""
This script generates Overhangs by stringing together Arcs, allowing successful fdm-3d-printing of large 90 deg overhangs!
The genius Idea is emerged from Steven McCulloch, who coded a demonstration and the basic mechanics: https://github.com/stmcculloch/arc-overhang
This python script builds up on that and offers a convinient way to integrate the ArcOverhangs into an existing gcode-file.
HOW TO USE: 
Option A) open your system console and type 'python ' followed by the path to this script and the path of the gcode file. Will overwrite the file.
Option B) open PrusaSlicer, go to print-settings-tab->output-options. Locate the window for post-processing-script. 
    In that window enter: full path to your python exe,emtyspace, full path to this script.
    If the python path contains any empty spaces, mask them as described here: https://manual.slic3r.org/advanced/post-processing
=>PrusaSlicer will execute the script after the export of the Gcode, therefore the view in the window wont change. Open the finished gcode file to see the results.
If you want to change generation settings: Scroll to 'Parameter' section. Settings from PrusaSlicer will be extracted automaticly from the gcode.
Requirements:
Python 3.5+ and the librarys: shapely 1.8+, numpy 1.2+, numpy-hilbert-curve matplotlib for debugging
Slicing in PrusaSlicer is mandatory.
Tested only in PrusaSlicer 2.5&Python 3.10, other versions might need adapted keywords.
Notes:
This code is a little messy. Usually I would devide it into multiple files, but that would compromise the ease of use.
Therefore I divided the code into sections, marked with ###
Feel free to give it some refactoring and add more functionalities!
Used Coding-Flavour: variable Names: smallStartEveryWordCapitalized, 'to' replaced by '2', same for "for"->"4". Parameters: BigStartEveryWordCapitalized
Known issues:
-pointsPerCircle>80 might give weird results
-MaxDistanceFromPerimeter >=2*perimeterwidth might weird result.
-avoid using the code multiple times onto the same gcode, since the bridge infill is deleted when the arcs are generated.
"""
#!/usr/bin/python
import sys
import os
import logging
from shapely import Point, Polygon, LineString, GeometryCollection, MultiLineString, MultiPolygon
from shapely.ops import nearest_points, linemerge, unary_union
import matplotlib.pyplot as plt
import numpy as np
from ast import literal_eval
import warnings
import random
import platform
from hilbert import decode, encode
import configparser

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def make_full_setting_dict(gcode_setting_dict: dict) -> dict:
    """Merge Two Dictionarys and set some keys/values explicitly"""
    add_manual_settings_dict = {
        "CheckForAllowedSpace": False,
        "AllowedSpaceForArcs": Polygon([[0, 0], [500, 0], [500, 500], [0, 500]]),
        "ArcCenterOffset": 2,
        "ArcMinPrintSpeed": 0.5 * 60,
        "ArcPrintSpeed": 1.5 * 60,
        "ArcTravelFeedRate": 30 * 60,
        "ExtendIntoPerimeter": 1.5 * gcode_setting_dict.get("perimeter_extrusion_width"),
        "MaxDistanceFromPerimeter": 2 * gcode_setting_dict.get("perimeter_extrusion_width"),
        "MinArea": 5 * 10,
        "MinBridgeLength": 5,
        "Path2Output": r"",
        "RMax": 110,
        "TimeLapseEveryNArcs": 0,
        "aboveArcsFanSpeed": 25,
        "aboveArcsInfillPrintSpeed": 10 * 60,
        "aboveArcsPerimeterFanSpeed": 25,
        "aboveArcsPerimeterPrintSpeed": 3 * 60,
        "applyAboveFanSpeedToWholeLayer": True,
        "CoolingSettingDetectionDistance": 5,
        "specialCoolingZdist": 3,
        "ArcExtrusionMultiplier": 1.35,
        "ArcSlowDownBelowThisDuration": 3,
        "ArcWidth": gcode_setting_dict.get("nozzle_diameter") * 0.95,
        "ArcFanSpeed": 255,
        "CornerImportanceMultiplier": 0.2,
        "DistanceBetweenPointsOnStartLine": 0.1,
        "GCodeArcPtMinDist": 0.1,
        "ExtendArcDist": 1.0,
        "HilbertFillingPercentage": 100,
        "HilbertInfillExtrusionMultiplier": 1.05,
        "HilbertTravelEveryNSeconds": 6,
        "MinStartArcs": 2,
        "PointsPerCircle": 80,
        "SafetyBreak_MaxArcNumber": 2000,
        "WarnBelowThisFillingPercentage": 90,
        "UseLeastAmountOfCenterPoints": True,
        "plotStart": False,
        "plotArcsEachStep": False,
        "plotArcsFinal": False,
        "plotDetectedInfillPoly": False,
        "plotEachHilbert": False,
        "PrintDebugVerification": False
    }
    gcode_setting_dict.update(add_manual_settings_dict)
    return gcode_setting_dict

def main(gcode_file_stream, path2gcode, skip_input) -> None:
    gcode_lines = gcode_file_stream.readlines()
    slicer_type = detect_slicer_type(gcode_lines)
    gcode_setting_dict = read_settings_from_gcode2dict(gcode_lines, {"Fallback_nozzle_diameter": 0.4, "Fallback_filament_diameter": 1.75}, slicer_type)
    parameters = make_full_setting_dict(gcode_setting_dict)
    if not check_for_necessary_settings(gcode_setting_dict, slicer_type):
        warnings.warn("Incompatible Slicer-Settings used!")
        input("Can not run script, gcode unmodified. Press enter to close.")
        raise ValueError("Incompatible Settings used!")
    layer_objs = []
    startup_lines = []
    gcode_was_modified = False
    if gcode_file_stream:
        layers = split_gcode_into_layers(gcode_lines)
        startup_lines = layers.pop(0)
        gcode_file_stream.close()
        logging.info(f"layers: {len(layers)}")
        last_fan_setting = 0
        for idl, layer_lines in enumerate(layers):
            layer = Layer(layer_lines, parameters, idl)
            layer.add_z()
            layer.add_height()
            last_fan_setting = layer.spot_fan_setting(last_fan_setting)
            layer_objs.append(layer)
        for idl, layer in enumerate(layer_objs):
            modify = False
            if idl < 1:
                continue
            else:
                layer.extract_features()
                layer.spot_bridge_infill()
                layer.make_polys_from_bridge_infill(extend=parameters.get("ExtendIntoPerimeter", 1))
                layer.polys = layer.merge_polys()
                layer.verify_infill_polys()
                if layer.validpolys:
                    modify = True
                    gcode_was_modified = True
                    logging.info(f"overhang found layer {idl}: {len(layer.polys)}, Z: {layer.z:.2f}")
                    max_z = layer.z + parameters.get("specialCoolingZdist")
                    id_offset = 1
                    curr_z = layer.z
                    while curr_z <= max_z and idl + id_offset <= len(layer_objs) - 1:
                        curr_z = layer_objs[idl + id_offset].z
                        layer_objs[idl + id_offset].oldpolys.extend(layer.validpolys)
                        id_offset += 1
                    prev_layer = layer_objs[idl - 1]
                    prev_layer.make_external_perimeter2polys()
                    arc_overhang_gcode = []
                    for poly in layer.validpolys:
                        max_distance_from_perimeter = parameters.get("MaxDistanceFromPerimeter")
                        r_max = parameters.get("RMax", 15)
                        points_per_circle = parameters.get("PointsPerCircle", 80)
                        arc_width = parameters.get("ArcWidth")
                        r_min = parameters.get("ArcCenterOffset") + arc_width / 1.5
                        r_min_start = parameters.get("nozzle_diameter")
                        final_arcs = []
                        arcs = []
                        arcs4gcode = []
                        start_line_string, boundary_without_start_line = prev_layer.make_start_line_string(poly, parameters)
                        if start_line_string is None:
                            warnings.warn("Skipping Polygon because no StartLine Found")
                            continue
                        start_pt = get_start_pt_on_ls(start_line_string, parameters)
                        remaining_space = poly
                        concentric_arcs = generate_multiple_concentric_arcs(start_pt, r_min_start, r_max, boundary_without_start_line, remaining_space, parameters)
                        if len(concentric_arcs) < parameters.get("MinStartArcs"):
                            start_pt = get_start_pt_on_ls(redistribute_vertices(start_line_string, 0.1), parameters)
                            concentric_arcs = generate_multiple_concentric_arcs(start_pt, r_min_start, r_max, boundary_without_start_line, remaining_space, parameters)
                            if len(concentric_arcs) < parameters.get("MinStartArcs"):
                                logging.info(f"Layer {idl}: Using random Startpoint")
                                for idr in range(10):
                                    start_pt = get_start_pt_on_ls(start_line_string, parameters, chose_random=True)
                                    concentric_arcs = generate_multiple_concentric_arcs(start_pt, r_min_start, r_max, boundary_without_start_line, remaining_space, parameters)
                                    if len(concentric_arcs) >= parameters.get("MinStartArcs"):
                                        break
                                if len(concentric_arcs) < parameters.get("MinStartArcs"):
                                    for idr in range(10):
                                        start_pt = get_start_pt_on_ls(redistribute_vertices(start_line_string, 0.1), parameters, chose_random=True)
                                        concentric_arcs = generate_multiple_concentric_arcs(start_pt, r_min_start, r_max, boundary_without_start_line, remaining_space, parameters)
                                        if len(concentric_arcs) >= parameters.get("MinStartArcs"):
                                            break
                                if len(concentric_arcs) < parameters.get("MinStartArcs"):
                                    warnings.warn("Initialization Error: no concentric Arc could be generated at startpoints, moving on")
                                    continue
                        arc_boundaries = get_arc_boundaries(concentric_arcs)
                        final_arcs.append(concentric_arcs[-1])
                        for arc in concentric_arcs:
                            remaining_space = remaining_space.difference(arc.poly.buffer(1e-2))
                            arcs.append(arc)
                        for arc_boundary in arc_boundaries:
                            arcs4gcode.append(arc_boundary)
                        idx = 0
                        safety_break = 0
                        tried_fixing = False
                        while idx < len(final_arcs):
                            sys.stdout.write("\033[F")
                            sys.stdout.write("\033[K")
                            logging.info(f"while executed: {idx}, {len(final_arcs)}")
                            cur_arc = final_arcs[idx]
                            if cur_arc.poly.geom_type == "MultiPolygon":
                                farthest_point_on_arc, longest_distance, nearest_point_on_poly = get_farthest_point(cur_arc.poly.geoms[0], poly, remaining_space)
                            else:
                                farthest_point_on_arc, longest_distance, nearest_point_on_poly = get_farthest_point(cur_arc.poly, poly, remaining_space)
                            if not farthest_point_on_arc or longest_distance < max_distance_from_perimeter:
                                idx += 1
                                continue
                            start_pt = move_toward_point(farthest_point_on_arc, cur_arc.center, parameters.get("ArcCenterOffset", 2))
                            concentric_arcs = generate_multiple_concentric_arcs(start_pt, r_min, r_max, poly.boundary, remaining_space, parameters)
                            arc_boundaries = get_arc_boundaries(concentric_arcs)
                            if len(concentric_arcs) > 0:
                                for arc in concentric_arcs:
                                    remaining_space = remaining_space.difference(arc.poly.buffer(1e-2))
                                    arcs.append(arc)
                                final_arcs.append(concentric_arcs[-1])
                                for arc_boundary in arc_boundaries:
                                    arcs4gcode.append(arc_boundary)
                            else:
                                idx += 1
                            safety_break += 1
                            if safety_break > parameters.get("SafetyBreak_MaxArcNumber", 2000):
                                break
                            if parameters.get("plotArcsEachStep"):
                                plt.title(f"Iteration {idx}, Total No Start Points: {len(final_arcs)}, Total No Arcs: {len(arcs)}")
                                plot_geometry(start_line_string, 'r')
                                plot_geometry([arc.poly for arc in arcs], changecolor=True)
                                plot_geometry(remaining_space, 'g', filled=True)
                                plot_geometry(start_pt, "r")
                                plt.axis('square')
                                plt.show()
                            if len(final_arcs) == 1 and idx == 1 and remaining_space.area / poly.area * 100 > 50 and not tried_fixing:
                                parameters["ArcCenterOffset"] = 0
                                r_min = arc_width / 1.5
                                idx = 0
                                tried_fixing = True
                                logging.info("the arc-generation got stuck at a thight spot during startup. Used Automated fix:set ArcCenterOffset to 0")
                            if tried_fixing and len(final_arcs) == 1 and idx == 1:
                                logging.info("fix did not work.")
                        remain2fill_percent = remaining_space.area / poly.area * 100
                        if remain2fill_percent > 100 - parameters.get("WarnBelowThisFillingPercentage"):
                            warnings.warn(f"layer {idl}: The Overhang Area is only {100 - remain2fill_percent:.0f}% filled with Arcs. Please try again with adapted Parameters: set 'ExtendIntoPerimeter' higher to enlargen small areas. lower the MaxDistanceFromPerimeter to follow the curvature more precise. Set 'ArcCenterOffset' to 0 to reach delicate areas.")
                        if parameters.get("plotArcsFinal"):
                            plt.title(f"Iteration {idx}, Total No Start Points: {len(final_arcs)}, Total No Arcs: {len(arcs)}")
                            plot_geometry(start_line_string, 'r')
                            plot_geometry([arc.poly for arc in arcs], changecolor=True)
                            plot_geometry(remaining_space, 'g', filled=True)
                            plot_geometry(start_pt, "r")
                            plt.axis('square')
                            plt.show()
                        e_steps_per_mm = calc_e_steps_per_mm(parameters)
                        arc_overhang_gcode.append(f"M106 S{np.round(parameters.get('bridge_fan_speed', 100) * 2.55)}\n")
                        for ida, arc in enumerate(arcs4gcode):
                            if not arc.is_empty:
                                arc_gcode = arc2gcode(arc, e_steps_per_mm, ida, parameters)
                                arc_overhang_gcode.append(arc_gcode)
                                if parameters.get("TimeLapseEveryNArcs") > 0:
                                    if ida % parameters.get("TimeLapseEveryNArcs"):
                                        arc_overhang_gcode.append("M240\n")
                if len(layer.oldpolys) > 0:
                    modify = True
                    logging.info(f"oldpolys found in layer: {idl}")
                    layer.spot_solid_infill()
                    layer.make_polys_from_solid_infill(extend=parameters.get("ExtendIntoPerimeter"))
                    layer.solid_polys = layer.merge_polys(layer.solid_polys)
                    all_hilbert_pts = []
                    for poly in layer.solid_polys:
                        hilbert_pts = layer.create_hilbert_curve_in_poly(poly)
                        all_hilbert_pts.extend(hilbert_pts)
                        if parameters.get("plotEachHilbert"):
                            plot_geometry(hilbert_pts, changecolor=True)
                            plot_geometry(layer.solid_polys)
                            plt.title("Debug")
                            plt.axis('square')
                            plt.show()
                if modify:
                    modified_layer = Layer([], parameters, idl)
                    is_injected = False
                    hilbert_is_injected = False
                    cur_print_speed = "G1 F600"
                    messed_with_speed = False
                    messed_with_fan = False
                    layer.prepare_deletion(featurename="Bridge", polys=layer.validpolys)
                    if len(layer.oldpolys) > 0:
                        layer.prepare_deletion(featurename=":Solid", polys=layer.oldpolys)
                    injection_start = None
                    logging.info("modifying GCode")
                    for idline, line in enumerate(layer.lines):
                        if layer.validpolys:
                            if ";TYPE" in line and not is_injected:
                                injection_start = idline
                                modified_layer.lines.append(";TYPE:Arc infill\n")
                                modified_layer.lines.append(f"M106 S{parameters.get('ArcFanSpeed')}\n")
                                for overhang_line in arc_overhang_gcode:
                                    for arc_line in overhang_line:
                                        for cmd_line in arc_line:
                                            modified_layer.lines.append(cmd_line)
                                is_injected = True
                                for id in reversed(range(injection_start)):
                                    if "X" in layer.lines[id]:
                                        modified_layer.lines.append(layer.lines[id])
                                        break
                        if layer.oldpolys:
                            if ";TYPE" in line and not hilbert_is_injected:
                                hilbert_is_injected = True
                                injection_start = idline
                                modified_layer.lines.append(";TYPE:Solid infill\n")
                                modified_layer.lines.append(f"M106 S{parameters.get('aboveArcsFanSpeed')}\n")
                                hilbert_gcode = hilbert2gcode(all_hilbert_pts, parameters, layer.height)
                                modified_layer.lines.extend(hilbert_gcode)
                                for id in reversed(range(injection_start)):
                                    if "X" in layer.lines[id]:
                                        modified_layer.lines.append(layer.lines[id])
                                        break
                        if "G1 F" in line.split(";")[0]:
                            cur_print_speed = line
                        if layer.export_this_line(idline):
                            if layer.is_close2bridging(line, parameters.get("CoolingSettingDetectionDistance")):
                                if not messed_with_fan:
                                    modified_layer.lines.append(f"M106 S{parameters.get('aboveArcsFanSpeed')}\n")
                                    messed_with_fan = True
                                mod_line = line.strip("\n") + f" F{parameters.get('aboveArcsPerimeterPrintSpeed')}\n"
                                modified_layer.lines.append(mod_line)
                                messed_with_speed = True
                            else:
                                if messed_with_fan and not parameters.get("applyAboveFanSpeedToWholeLayer"):
                                    modified_layer.lines.append(f"M106 S{layer.fan_setting:.0f}\n")
                                    messed_with_fan = False
                                if messed_with_speed:
                                    modified_layer.lines.append(cur_print_speed + "\n")
                                    messed_with_speed = False
                                modified_layer.lines.append(line)
                    if messed_with_fan:
                        modified_layer.lines.append(f"M106 S{layer.fan_setting:.0f}\n")
                        messed_with_fan = False
                    layer_objs[idl] = modified_layer
    if gcode_was_modified:
        overwrite = True
        if parameters.get("Path2Output"):
            path2gcode = parameters.get("Path2Output")
            overwrite = False
        with open(path2gcode, "w") as f:
            if overwrite:
                logging.info("overwriting file")
            else:
                logging.info(f"write to {path2gcode}")
            f.writelines(startup_lines)
            for layer in layer_objs:
                f.writelines(layer.lines)
    else:
        logging.info(f"Analysed {len(layer_objs)} Layers, but no matching overhangs found->no arcs generated. If unexpected: look if restricting settings like 'minArea' or 'MinBridgeLength' are correct.")
    logging.info("Script execution complete.")
    if not skip_input:
        input("Press enter to exit.")

def get_file_stream_and_path(read=True):
    if len(sys.argv) != 2:
        logging.error("Usage: python3 ex1.py <filename>")
        sys.exit(1)
    filepath = sys.argv[1]
    try:
        if read:
            f = open(filepath, "r")
        else:
            f = open(filepath, "w")
        return f, filepath
    except IOError:
        input("File not found. Press enter.")
        sys.exit(1)

def split_gcode_into_layers(gcode: list) -> list:
    gcode_list = []
    buff = []
    for linenumber, line in enumerate(gcode):
        if ";LAYER_CHANGE" in line:
            gcode_list.append(buff)
            buff = []
            buff.append(line)
        else:
            buff.append(line)
    gcode_list.append(buff)
    logging.info(f"last read linenumber: {linenumber}")
    return gcode_list

def get_pt_from_cmd(line: str) -> Point:
    x = None
    y = None
    line = line.split(";")[0]
    cmds = line.split(" ")
    for c in cmds:
        if "X" in c:
            x = float(c[1:])
        elif "Y" in c:
            y = float(c[1:])
    if (x is not None) and (y is not None):
        p = Point(x, y)
    else:
        p = None
    return p

def make_polygon_from_gcode(lines: list) -> Polygon:
    pts = []
    for line in lines:
        if ";WIPE" in line:
            break
        if "G1" in line:
            p = get_pt_from_cmd(line)
            if p:
                pts.append(p)
    if len(pts) > 2:
        return Polygon(pts)
    else:
        return None

class Layer:
    def __init__(self, lines: list = [], kwargs: dict = {}, layer_number: int = -1) -> None:
        self.lines = lines
        self.layer_number = layer_number
        self.z = kwargs.get("z", None)
        self.polys = []
        self.validpolys = []
        self.ext_perimeter_polys = []
        self.binfills = []
        self.features = []
        self.oldpolys = []
        self.dont_perform_perimeter_check = kwargs.get('notPerformPerimeterCheck', False)
        self.delete_these_infills = []
        self.delete_lines = []
        self.associated_ids = []
        self.sinfills = []
        self.parameters = kwargs
        self.last_p = None

    def extract_features(self) -> None:
        buff = []
        current_type = ""
        start = 0
        for idl, line in enumerate(self.lines):
            if ";TYPE:" in line:
                if current_type:
                    self.features.append([current_type, buff, start])
                    buff = []
                    start = idl
                current_type = line
            else:
                buff.append(line)
        self.features.append([current_type, buff, start])

    def add_z(self, z: float = None) -> None:
        if z:
            self.z = z
        else:
            for l in self.lines:
                cmd = l.split(";")[0]
                if "G1" in cmd and "Z" in cmd:
                    cmds = cmd.split(" ")
                    for c in cmds:
                        if "Z" in c:
                            self.z = float(c[1:])
                            return

    def add_height(self):
        for l in self.lines:
            if ";HEIGHT" in l:
                h = l.split(":")
                self.height = float(h[-1])
                return
        warnings.warn(f"Layer {self.layer_number}: no height found, using layerheight default!")
        self.height = self.parameters.get("layer_height")

    def get_real_feature_start_point(self, idf: int) -> Point:
        if idf < 1:
            return None
        lines = self.features[idf - 1][1]
        for line in reversed(lines):
            if "G1" in line:
                return get_pt_from_cmd(line)

    def make_external_perimeter2polys(self) -> None:
        ext_perimeter_is_started = False
        for idf, fe in enumerate(self.features):
            ftype = fe[0]
            lines = fe[1]
            if "External" in ftype or ("Overhang" in ftype and ext_perimeter_is_started) or ("Overhang" in ftype and self.dont_perform_perimeter_check):
                if not ext_perimeter_is_started:
                    lines_with_start = []
                    if idf > 1:
                        pt = self.get_real_feature_start_point(idf)
                        if type(pt) == type(Point):
                            lines_with_start.append(p2gcode(pt))
                        else:
                            warnings.warn(f"Layer {self.layer_number}: Could not fetch real StartPoint.")
                lines_with_start = lines_with_start + lines
                ext_perimeter_is_started = True
            if (idf == len(self.features) - 1 and ext_perimeter_is_started) or (ext_perimeter_is_started and not ("External" in ftype or "Overhang" in ftype)):
                poly = make_polygon_from_gcode(lines_with_start)
                if poly:
                    self.ext_perimeter_polys.append(poly)
                ext_perimeter_is_started = False

    def make_start_line_string(self, poly: Polygon, kwargs: dict = {}):
        if not self.ext_perimeter_polys:
            self.make_external_perimeter2polys()
        if len(self.ext_perimeter_polys) < 1:
            warnings.warn(f"Layer {self.layer_number}: No ExternalPerimeterPolys found in prev Layer")
            return None, None
        for ep in self.ext_perimeter_polys:
            ep = ep.buffer(1e-2)
            if ep.intersects(poly):
                start_area = ep.intersection(poly)
                start_line_string = start_area.boundary.intersection(poly.boundary.buffer(1e-2))
                if start_line_string.is_empty:
                    if poly.contains(start_area):
                        start_line_string = start_area.boundary
                        boundary_line_string = poly.boundary
                        if start_line_string.is_empty:
                            plt.title("StartLineString is None")
                            plot_geometry(poly, 'b')
                            plot_geometry(start_area, filled=True)
                            plot_geometry([ep for ep in self.ext_perimeter_polys])
                            plt.legend(["currentLayerPoly", "StartArea", "prevLayerPoly"])
                            plt.axis('square')
                            plt.show()
                            warnings.warn(f"Layer {self.layer_number}: No Intersection in Boundary,Poly+ExternalPoly")
                            return None, None
                else:
                    boundary_line_string = poly.boundary.difference(start_area.boundary.buffer(1e-2))
                if kwargs.get("plotStart"):
                    plot_geometry(poly, color="b")
                    plot_geometry(ep, 'g')
                    plot_geometry(start_line_string, color="m")
                    plt.title("Start-Geometry")
                    plt.legend(["Poly4ArcOverhang", "External Perimeter prev Layer", "StartLine for Arc Generation"])
                    plt.axis('square')
                    plt.show()
                return start_line_string, boundary_line_string
        plt.title("no intersection with prev Layer Boundary")
        plot_geometry(poly, 'b')
        plot_geometry([ep for ep in self.ext_perimeter_polys])
        plt.legend(["currentLayerPoly", "prevLayerPoly"])
        plt.axis('square')
        plt.show()
        warnings.warn(f"Layer {self.layer_number}: No intersection with prevLayer External Perimeter detected")
        return None, None

    def merge_polys(self, these_polys: list = None) -> list:
        if not these_polys:
            these_polys = self.polys
        merged_polys = unary_union(these_polys)
        if merged_polys.geom_type == "Polygon":
            these_polys = [merged_polys]
        elif merged_polys.geom_type == "MultiPolygon" or merged_polys.geom_type == "GeometryCollection":
            these_polys = [poly for poly in merged_polys.geoms]
        return these_polys

    def spot_feature_points(self, feature_name: str, split_at_wipe=False, include_real_start_pt=False, split_at_travel=False) -> list:
        parts = []
        for idf, fe in enumerate(self.features):
            ftype = fe[0]
            lines = fe[1]
            start = fe[2]
            pts = []
            is_wipe_move = False
            travel_str = f"F{self.parameters.get('travel_speed') * 60}"
            if feature_name in ftype:
                if include_real_start_pt and idf > 0:
                    sp = self.get_real_feature_start_point(idf)
                    if sp: pts.append(sp)
                for line in lines:
                    if "G1" in line and (not is_wipe_move):
                        if (not "E" in line) and travel_str in line and split_at_travel:
                            if len(pts) >= 2:
                                parts.append(pts)
                                pts = []
                        elif "E" in line:
                            p = get_pt_from_cmd(line)
                            if p:
                                pts.append(p)
                    if 'WIPE_START' in line:
                        is_wipe_move = True
                        if split_at_wipe:
                            parts.append(pts)
                            pts = []
                    if 'WIPE_END' in line:
                        is_wipe_move = False
                if len(pts) > 1:
                    parts.append(pts)
        return parts

    def spot_solid_infill(self) -> None:
        parts = self.spot_feature_points("Solid infill", split_at_travel=True)
        for infill_pts in parts:
            if self.verify_solid_infill_pts(infill_pts):
                self.sinfills.append(LineString(infill_pts))

    def make_polys_from_solid_infill(self, extend: float = 1) -> None:
        self.solid_polys = []
        for s_infill in self.sinfills:
            infill_poly = s_infill.buffer(extend)
            self.solid_polys.append(infill_poly)
            if self.parameters.get("plotDetectedSolidInfillPoly"):
                plot_geometry(infill_poly)
                plot_geometry(s_infill, "g")
                plt.axis('square')
                plt.show()

    def verify_solid_infill_pts(self, infill_pts: list) -> bool:
        for p in infill_pts:
            for poly in self.oldpolys:
                if poly.contains(p):
                    return True
        return False

    def spot_bridge_infill(self) -> None:
        parts = self.spot_feature_points("Bridge infill", split_at_travel=True)
        for idf, infill_pts in enumerate(parts):
            self.binfills.append(BridgeInfill(infill_pts))

    def make_polys_from_bridge_infill(self, extend: float = 1) -> None:
        for b_infill in self.binfills:
            infill_pts = b_infill.pts
            infill_ls = LineString(infill_pts)
            infill_poly = infill_ls.buffer(extend)
            self.polys.append(infill_poly)
            self.associated_ids.append(b_infill.id)
            if self.parameters.get("plotDetectedInfillPoly"):
                plot_geometry(infill_poly)
                plot_geometry(infill_ls, "g")
                plt.axis('square')
                plt.show()

    def get_overhang_perimeter_line_strings(self):
        parts = self.spot_feature_points("Overhang perimeter", include_real_start_pt=True)
        if parts:
            return [LineString(pts) for pts in parts]
        else:
            return []

    def verify_infill_polys(self, min_dist_for_validation: float = 0.5) -> None:
        overhangs = self.get_overhang_perimeter_line_strings()
        if len(overhangs) > 0:
            allowed_space_polygon = self.parameters.get("AllowedSpaceForArcs")
            if not allowed_space_polygon:
                input(f"Layer {self.layer_number}: no allowed space Polygon provided to layer obj, unable to run script. Press Enter.")
                raise ValueError(f"Layer {self.layer_number}: no allowed space Polygon provided to layer obj")
            for idp, poly in enumerate(self.polys):
                if not poly.is_valid:
                    continue
                if (not allowed_space_polygon.contains(poly)) and self.parameters.get("CheckForAllowedSpace"):
                    continue
                if poly.area < self.parameters.get("MinArea"):
                    continue
                for ohp in overhangs:
                    if poly.distance(ohp) < min_dist_for_validation:
                        if ohp.length > self.parameters.get("MinBridgeLength"):
                            self.validpolys.append(poly)
                            self.delete_these_infills.append(idp)
                            break

    def prepare_deletion(self, featurename: str = "Bridge", polys: list = None) -> None:
        if not polys:
            polys = self.validpolys
        for idf, fe in enumerate(self.features):
            ftype = fe[0]
            lines = fe[1]
            start = fe[2]
            delete_this = False
            if featurename in ftype:
                for poly in polys:
                    for line in lines:
                        p = get_pt_from_cmd(line)
                        if p:
                            if poly.contains(p):
                                delete_this = True
                                break
                        if delete_this:
                            break
                if delete_this:
                    if idf < len(self.features) - 1:
                        end = self.features[idf + 1][2] - 1
                    else:
                        end = len(self.lines)
                    self.delete_lines.append([start, end])

    def export_this_line(self, linenumber: int) -> bool:
        export = True
        if len(self.delete_lines) > 0:
            for d in self.delete_lines:
                if linenumber >= d[0] and linenumber <= d[1]:
                    export = False
        return export

    def create_hilbert_curve_in_poly(self, poly: Polygon):
        dimensions = 2
        w = self.parameters.get("solid_infill_extrusion_width")
        a = self.parameters.get("HilbertFillingPercentage") / 100
        mm_between_travels = (self.parameters.get("aboveArcsInfillPrintSpeed") / 60) * self.parameters.get("HilbertTravelEveryNSeconds")
        min_x, min_y, max_x, max_y = poly.bounds
        lx = max_x - min_x
        ly = max_y - min_y
        l = max(lx, ly)
        iteration_count = int(np.ceil(np.log((a * l + w) / w) / np.log(2)))
        scale = w / a
        max_idx = int(2 ** (dimensions * iteration_count) - 1)
        locs = decode(np.arange(max_idx), 2, iteration_count)
        mov_x = self.layer_number % 2 * w / a
        mov_y = self.layer_number % 2 * w / a
        x = locs[:, 0] * scale + min_x - mov_x
        y = locs[:, 1] * scale + min_y - mov_y
        hilbert_points_raw = [[xi, yi] for xi, yi in zip(x.tolist(), y.tolist())]
        no_el = int(np.ceil(mm_between_travels / scale))
        buff = []
        composite_list = []
        for el in hilbert_points_raw:
            p = Point(el)
            if p.within(poly):
                buff.append(p)
            else:
                if len(buff) > 5:
                    if len(buff) > no_el * 1.7:
                        composite_list.extend([buff[x:x + no_el] for x in range(0, len(buff), no_el)])
                    else:
                        composite_list.append(buff)
                buff = []
        if len(buff) > 5:
            composite_list.append(buff)
        random.shuffle(composite_list)
        return composite_list

    def is_close2bridging(self, line: str, min_detection_distance: float = 3):
        if not "G1" in line:
            return False
        p = get_pt_from_cmd(line)
        if not p:
            return False
        if not self.last_p:
            self.last_p = Point(p.x - 0.01, p.y - 0.01)
        ls = LineString([p, self.last_p])
        self.last_p = p
        for poly in self.oldpolys:
            if ls.distance(poly) < min_detection_distance:
                return True
        return False

    def spot_fan_setting(self, last_fan_setting: float):
        for line in self.lines:
            if "M106" in line.split(";")[0]:
                svalue = line.strip("\n").split(";")[0].split(" ")[1]
                self.fan_setting = float(svalue[1:])
                return self.fan_setting
        self.fan_setting = last_fan_setting
        return last_fan_setting

class Arc:
    def __init__(self, center: Point, r: float, kwargs: dict = {}) -> None:
        self.center = center
        self.r = r
        self.points_per_circle = kwargs.get("PointsPerCircle", 80)
        self.parameters = kwargs

    def set_poly(self, poly: Polygon) -> None:
        self.poly = poly

    def extract_arc_boundary(self):
        circ = create_circle(self.center, self.r, self.points_per_circle)
        true_arc = self.poly.boundary.intersection(circ.boundary.buffer(1e-2))
        if true_arc.geom_type == 'MultiLineString':
            merged = linemerge(true_arc)
        elif true_arc.geom_type == 'LineString':
            self.arcline = true_arc
            return true_arc
        else:
            merged = linemerge(MultiLineString([l for l in true_arc.geoms if l.geom_type == 'LineString']))
        if merged.geom_type == "LineString":
            self.arcline = merged
            return merged
        elif merged.geom_type == "MultiLineString":
            arc_list = []
            for ls in merged.geoms:
                arc = Arc(self.center, self.r, self.parameters)
                arc.arcline = ls
                arc_list.append(arc)
            return arc_list
        else:
            input("ArcBoundary merging Error. Unable to run script. Press Enter.")
            raise ValueError("ArcBoundary merging Error")

    def generate_concentric_arc(self, start_pt: Point, remaining_space: Polygon) -> Polygon:
        circ = create_circle(start_pt, self.r, self.points_per_circle)
        arc = circ.intersection(remaining_space)
        self.poly = arc
        return arc

class BridgeInfill:
    def __init__(self, pts=[], id=random.randint(1, int(1e10))) -> None:
        self.pts = pts
        self.delete_later = False
        self.id = id

def midpoint(p1: Point, p2: Point):
    return Point((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)

def get_start_pt_on_ls(ls: LineString, kwargs: dict = {}, chose_random: bool = False) -> Point:
    if ls.geom_type == "MultiLineString" or ls.geom_type == "GeometryCollection":
        lengths = []
        for lss in ls.geoms:
            if lss.geom_type == "LineString":
                lengths.append(lss.length)
            else:
                lengths.append(0)
        ls_idx = np.argmax(lengths)
        if not ls_idx.is_integer():
            try:
                ls_idx = ls_idx[0]
            except:
                ls_idx = 0
        ls = ls.geoms[ls_idx]
    if len(ls.coords) < 2:
        warnings.warn("Start LineString with <2 Points invalid")
        input("Can not run script, gcode unmodified. Press Enter")
        raise ValueError("Start LineString with <2 Points invalid")
    if len(ls.coords) == 2:
        return midpoint(Point(ls.coords[0]), Point(ls.coords[1]))
    scores = []
    cur_length = 0
    pts = [Point(p) for p in ls.coords]
    if chose_random:
        return random.choice(pts)
    coords = [np.array(p) for p in ls.coords]
    for idp, p in enumerate(pts):
        if idp == 0 or idp == len(pts) - 1:
            scores.append(0)
            continue
        cur_length += p.distance(pts[idp - 1])
        rel_length = cur_length / ls.length
        length_score = 1 - np.abs(rel_length - 0.5)
        v1 = coords[idp] - coords[idp - 1]
        v2 = coords[idp + 1] - coords[idp]
        if np.linalg.norm(v1) > 0 and np.linalg.norm(v2) > 0:
            v1 = v1 / np.linalg.norm(v1)
            v2 = v2 / np.linalg.norm(v2)
            angle_score = np.abs(np.sin(np.arccos(np.clip(np.dot(v1, v2), -1.0, 1.0))))
            angle_score *= kwargs.get("CornerImportanceMultiplier", 1)
            scores.append(length_score + angle_score)
        else:
            scores.append(length_score)
    max_index = scores.index(max(scores))
    return pts[max_index]

def create_circle(p: Point, radius: float, n: int) -> Polygon:
    x = p.x
    y = p.y
    return Polygon([[radius * np.sin(theta) + x, radius * np.cos(theta) + y] for theta in np.linspace(0, 2 * np.pi - 2 * np.pi / n, int(n))])

def get_farthest_point(arc: Polygon, base_poly: Polygon, remaining_empty_space: Polygon):
    longest_distance = -1
    farthest_point = Point([0, 0])
    point_found = False
    if arc.geom_type == 'Polygon':
        arc_coords = arc.exterior.coords
    elif arc.geom_type == 'LineString':
        arc_coords = np.linspace(list(arc.coords)[0], list(arc.coords)[1])
    else:
        plt.title("Function get_farthest_point went wrong")
        plot_geometry(base_poly, "b")
        plot_geometry(arc, "r")
        plt.axis('square')
        plt.show()
    for p in list(arc_coords):
        distance = Point(p).distance(base_poly.boundary)
        if (distance > longest_distance) and ((remaining_empty_space.buffer(1e-2).contains(Point(p)))):
            longest_distance = distance
            farthest_point = Point(p)
            point_found = True
    point_on_poly = nearest_points(base_poly, farthest_point)[0]
    if point_found:
        return farthest_point, longest_distance, point_on_poly
    else:
        return None, None, None

def move_toward_point(start_point: Point, target_point: Point, distance: float) -> Point:
    dx = target_point.x - start_point.x
    dy = target_point.y - start_point.y
    magnitude = (dx ** 2 + dy ** 2) ** 0.5
    dx /= magnitude
    dy /= magnitude
    return Point(start_point.x + dx * distance, start_point.y + dy * distance)

def redistribute_vertices(geom: LineString, distance: float) -> LineString:
    if geom.geom_type == 'LineString':
        num_vert = int(round(geom.length / distance))
        if num_vert == 0:
            num_vert = 1
        return LineString(
            [geom.interpolate(float(n) / num_vert, normalized=True)
             for n in range(num_vert + 1)])
    elif geom.geom_type == 'MultiLineString':
        parts = [redistribute_vertices(part, distance) for part in geom.geoms]
        return type(geom)([p for p in parts if not p.is_empty])
    else:
        warnings.warn('unhandled geometry %s', (geom.geom_type,))
        return geom

def generate_multiple_concentric_arcs(start_pt: Point, r_min: float, r_max: float, boundary_line_string: LineString, remaining_space: Polygon, kwargs={}) -> list:
    arcs = []
    r = r_min
    while r <= r_max:
        arc_obj = Arc(start_pt, r, kwargs=kwargs)
        arc = arc_obj.generate_concentric_arc(start_pt, remaining_space)
        if arc.intersects(boundary_line_string) and not kwargs.get("UseLeastAmountOfCenterPoints", False):
            break
        arcs.append(arc_obj)
        r += kwargs.get("ArcWidth")
    return arcs

def get_value_based_color(val: float, max_val=10) -> tuple:
    normalized_val = val / max_val
    rgb = [0, 0, 0]
    rgb[0] = min(normalized_val, 1)
    rgb[2] = 1 - rgb[0]
    return tuple(rgb)

def plot_geometry(geometry, color='black', linewidth=1, **kwargs):
    if type(geometry) == type([]):
        for idx, geo in enumerate(geometry):
            if kwargs.get("changecolor"):
                color = get_value_based_color(idx, len(geometry))
            plot_geometry(geo, color=color, linewidth=linewidth, kwargs=kwargs)
    elif geometry.geom_type == 'Point':
        x, y = geometry.x, geometry.y
        plt.scatter(x, y, color=color, linewidth=linewidth)
    elif geometry.geom_type == 'LineString':
        x, y = geometry.xy
        plt.plot(x, y, color=color, linewidth=linewidth)
    elif geometry.geom_type == 'Polygon':
        x, y = geometry.exterior.xy
        plt.plot(x, y, color=color, linewidth=linewidth)
        if kwargs.get("filled"):
            plt.fill(x, y, color=color, alpha=0.8)
        for interior in geometry.interiors:
            x, y = interior.xy
            plt.plot(x, y, color=color, linewidth=linewidth)
            if kwargs.get("filled_holes"):
                plt.fill(x, y, color=color, alpha=0.5)
    elif geometry.geom_type == 'MultiLineString':
        for line in geometry.geoms:
            x, y = line.xy
            plt.plot(x, y, color=color, linewidth=linewidth)
    elif geometry.geom_type == 'MultiPolygon' or geometry.geom_type == "GeometryCollection":
        for polygon in geometry.geoms:
            plot_geometry(polygon, color=color, linewidth=linewidth, kwargs=kwargs)
    else:
        logging.error('Unhandled geometry type: ' + geometry.geom_type)

def get_arc_boundaries(concentric_arcs: list) -> list:
    boundaries = []
    for arc in concentric_arcs:
        arc_line = arc.extract_arc_boundary()
        if type(arc_line) == type([]):
            for arc in arc_line:
                boundaries.append(arc.arcline)
        else:
            boundaries.append(arc_line)
    return boundaries

def read_settings_from_gcode2dict(gcode_lines: list, fallback_values_dict: dict, slicer_type: str) -> dict:
    gcode_setting_dict = fallback_values_dict
    is_setting = False
    for line in gcode_lines:
        if slicer_type == "PrusaSlicer" and "; prusaslicer_config = begin" in line:
            is_setting = True
            continue
        elif slicer_type == "OrcaSlicer" and "; orcaslicer_config = begin" in line:
            is_setting = True
            continue
        if is_setting:
            setting = line.strip(";").strip("\n").split("= ", 1)
            if len(setting) == 2:
                try:
                    gcode_setting_dict[setting[0].strip(" ")] = literal_eval(setting[1])
                except:
                    gcode_setting_dict[setting[0].strip(" ")] = setting[1]
            else:
                logging.warning(f"Could not read setting from {slicer_type}: {setting}")
    if "%" in str(gcode_setting_dict.get("perimeter_extrusion_width")):
        gcode_setting_dict["perimeter_extrusion_width"] = gcode_setting_dict.get("nozzle_diameter") * (float(gcode_setting_dict.get("perimeter_extrusion_width").strip("%")) / 100)
    is_warned = False
    for key, val in gcode_setting_dict.items():
        if isinstance(val, tuple):
            if gcode_setting_dict.get("Fallback_" + key):
                gcode_setting_dict[key] = gcode_setting_dict.get("Fallback_" + key)
            else:
                gcode_setting_dict[key] = val[0]
                if not is_warned:
                    warnings.warn(f"{key} was specified as tuple/list, this is normal for using multiple extruders. For all list values First values will be used. If unhappy: Add manual fallback value by searching for ADD FALLBACK in the code. And add 'Fallback_<key>:<yourValue>' into the dictionary.")
                    is_warned = True
    return gcode_setting_dict

def check_for_necessary_settings(gcode_setting_dict: dict, slicer_type: str) -> bool:
    if not gcode_setting_dict.get("use_relative_e_distances"):
        warnings.warn("Script only works with relative e-distances enabled in the slicer. Change accordingly.")
        return False
    if gcode_setting_dict.get("extrusion_width") < 0.001 or gcode_setting_dict.get("perimeter_extrusion_width") < 0.001 or gcode_setting_dict.get("solid_infill_extrusion_width") < 0.001:
        warnings.warn("Script only works with extrusion_width and perimeter_extrusion_width and solid_infill_extrusion_width>0. Change in the slicer accordingly.")
        return False
    if not gcode_setting_dict.get("overhangs"):
        warnings.warn("Overhang detection disabled in the slicer. Activate in the slicer for script success!")
        return False
    if gcode_setting_dict.get("bridge_speed") > 5:
        warnings.warn(f"Your Bridging Speed is set to {gcode_setting_dict.get('bridge_speed'):.0f} mm/s in the slicer. This can cause problems with warping.<=5mm/s is recommended")
    if gcode_setting_dict.get("infill_first"):
        warnings.warn("Infill set in the slicer to be printed before perimeter. This can cause problems with the script.")
    if gcode_setting_dict.get("external_perimeters_first"):
        warnings.warn("Slicer-Setting: External perimeter is printed before inner perimeters. Change for better overhang performance.")
    if not gcode_setting_dict.get("avoid_crossing_perimeters"):
        warnings.warn("Slicer-Setting: Travel Moves may cross the outline and therefore cause artefacts in arc generation.")
    return True

def calc_e_steps_per_mm(settings_dict: dict, layer_height: float = None) -> float:
    if layer_height:
        w = settings_dict.get("infill_extrusion_width")
        h = layer_height
        e_vol = (w - h) * h + np.pi * (h / 2) ** 2 * settings_dict.get("HilbertInfillExtrusionMultiplier", 1)
    else:
        e_vol = (settings_dict.get("nozzle_diameter") / 2) ** 2 * np.pi * settings_dict.get("ArcExtrusionMultiplier", 1)
    if settings_dict.get("use_volumetric_e"):
        return e_vol
    else:
        e_in_mm = e_vol / ((settings_dict.get("filament_diameter") / 2) ** 2 * np.pi)
        return e_in_mm

def p2gcode(p: Point, E=0, **kwargs) -> str:
    line = f"G1 X{p.x:.6} Y{p.y:.6} "
    line += "E0" if E == 0 else f"E{E:.7f}"
    if kwargs.get('F'):
        line += f" F{kwargs.get('F'):0d}"
    line += '\n'
    return line

def retract_gcode(retract: bool = True, kwargs: dict = {}) -> str:
    retract_dist = kwargs.get("retract_length", 1)
    E = -retract_dist if retract else retract_dist
    return f"G1 E{E} F{kwargs.get('retract_speed', 35) * 60}\n"

def set_feed_rate_gcode(F: int) -> str:
    return f"G1 F{F}\n"

def arc2gcode(arc_line: LineString, e_steps_per_mm: float, arc_idx=None, kwargs={}) -> list:
    gcode_lines = []
    p1 = None
    pts = [Point(p) for p in arc_line.coords]
    if len(pts) < 2:
        return []
    ext_dist = kwargs.get("ExtendArcDist", 0.5)
    p_extend = move_toward_point(pts[-2], pts[-1], ext_dist)
    arc_print_speed = np.clip(arc_line.length / (kwargs.get("ArcSlowDownBelowThisDuration", 3)) * 60,
                              kwargs.get("ArcMinPrintSpeed", 1 * 60), kwargs.get('ArcPrintSpeed', 2 * 60))
    for idp, p in enumerate(pts):
        if idp == 0:
            p1 = p
            gcode_lines.append(f";Arc {arc_idx if arc_idx else ' '} Length:{arc_line.length}\n")
            gcode_lines.append(p2gcode(p, F=kwargs.get('ArcTravelFeedRate', 100 * 60)))
            gcode_lines.append(retract_gcode(retract=False, kwargs=kwargs))
            gcode_lines.append(set_feed_rate_gcode(arc_print_speed))
        else:
            dist = p.distance(p1)
            if dist > kwargs.get("GCodeArcPtMinDist", 0.1):
                gcode_lines.append(p2gcode(p, E=dist * e_steps_per_mm))
                p1 = p
        if idp == len(pts) - 1:
            gcode_lines.append(p2gcode(p_extend, E=ext_dist * e_steps_per_mm))
            gcode_lines.append(retract_gcode(retract=True, kwargs=kwargs))
    return gcode_lines

def hilbert2gcode(all_hilbert_pts: list, parameters: dict, layer_height: float):
    hilbert_gcode = []
    e_steps_per_mm = calc_e_steps_per_mm(parameters, layer_height)
    for idc, curve_pts in enumerate(all_hilbert_pts):
        for idp, p in enumerate(curve_pts):
            if idp == 0:
                hilbert_gcode.append(p2gcode(p, F=parameters.get("ArcTravelFeedRate")))
                if idc == 0:
                    hilbert_gcode.append(retract_gcode(False, parameters))
            elif idp == 1:
                hilbert_gcode.append(p2gcode(p, E=e_steps_per_mm * p.distance(last_p), F=parameters.get("aboveArcsInfillPrintSpeed")))
            else:
                hilbert_gcode.append(p2gcode(p, E=e_steps_per_mm * p.distance(last_p)))
            last_p = p
    hilbert_gcode.append(retract_gcode(True, parameters))
    return hilbert_gcode

def detect_slicer_type(gcode_lines: list) -> str:
    for line in gcode_lines:
        if "; generated by PrusaSlicer" in line:
            return "PrusaSlicer"
        elif "; generated by OrcaSlicer" in line:
            return "OrcaSlicer"
    return "Unknown"

def _warning(message, category=UserWarning, filename='', lineno=-1, *args, **kwargs):
    logging.warning(f"{filename}:{lineno}: {message}")

warnings.showwarning = _warning

if __name__ == "__main__":
    gcode_file_stream, path2gcode = get_file_stream_and_path()
    skip_input = False
    if platform.system() != "Windows":
        skip_input = True
    main(gcode_file_stream, path2gcode, skip_input)
