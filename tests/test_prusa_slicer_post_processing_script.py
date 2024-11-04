import unittest
from unittest.mock import patch, mock_open, MagicMock
import prusa_slicer_post_processing_script as psp

class TestPrusaSlicerPostProcessingScript(unittest.TestCase):

    def setUp(self):
        self.gcode_lines = [
            ";LAYER_CHANGE\n",
            "G1 X0 Y0 Z0.3\n",
            ";TYPE:Bridge infill\n",
            "G1 X10 Y10 E0.5\n",
            "G1 X20 Y20 E0.5\n",
            ";LAYER_CHANGE\n",
            "G1 X0 Y0 Z0.6\n",
            ";TYPE:External perimeter\n",
            "G1 X10 Y10 E0.5\n",
            "G1 X20 Y20 E0.5\n"
        ]
        self.gcode_setting_dict = {
            "perimeter_extrusion_width": 0.4,
            "nozzle_diameter": 0.4,
            "use_relative_e_distances": True,
            "extrusion_width": 0.4,
            "solid_infill_extrusion_width": 0.4,
            "overhangs": True,
            "bridge_speed": 5,
            "infill_first": False,
            "external_perimeters_first": False,
            "avoid_crossing_perimeters": True
        }
        self.parameters = psp.make_full_setting_dict(self.gcode_setting_dict)

    def test_make_full_setting_dict(self):
        result = psp.make_full_setting_dict(self.gcode_setting_dict)
        self.assertIn("CheckForAllowedSpace", result)
        self.assertIn("ArcCenterOffset", result)
        self.assertEqual(result["ArcCenterOffset"], 2)

    def test_split_gcode_into_layers(self):
        result = psp.split_gcode_into_layers(self.gcode_lines)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], ";LAYER_CHANGE\n")
        self.assertEqual(result[1][0], "G1 X0 Y0 Z0.3\n")

    def test_get_pt_from_cmd(self):
        line = "G1 X10 Y20 E0.5\n"
        result = psp.get_pt_from_cmd(line)
        self.assertEqual(result.x, 10)
        self.assertEqual(result.y, 20)

    def test_make_polygon_from_gcode(self):
        result = psp.make_polygon_from_gcode(self.gcode_lines)
        self.assertIsNotNone(result)
        self.assertEqual(result.geom_type, "Polygon")

    def test_layer_add_z(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.add_z()
        self.assertEqual(layer.z, 0.3)

    def test_layer_add_height(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.add_height()
        self.assertEqual(layer.height, 0.2)

    def test_layer_extract_features(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        self.assertEqual(len(layer.features), 2)
        self.assertEqual(layer.features[0][0], ";TYPE:Bridge infill\n")

    def test_layer_make_external_perimeter2polys(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.make_external_perimeter2polys()
        self.assertEqual(len(layer.ext_perimeter_polys), 1)

    def test_layer_spot_bridge_infill(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.spot_bridge_infill()
        self.assertEqual(len(layer.binfills), 1)

    def test_layer_make_polys_from_bridge_infill(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.spot_bridge_infill()
        layer.make_polys_from_bridge_infill()
        self.assertEqual(len(layer.polys), 1)

    def test_layer_verify_infill_polys(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.spot_bridge_infill()
        layer.make_polys_from_bridge_infill()
        layer.verify_infill_polys()
        self.assertEqual(len(layer.validpolys), 1)

    def test_layer_prepare_deletion(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.spot_bridge_infill()
        layer.make_polys_from_bridge_infill()
        layer.verify_infill_polys()
        layer.prepare_deletion()
        self.assertEqual(len(layer.delete_lines), 1)

    def test_layer_export_this_line(self):
        layer = psp.Layer(self.gcode_lines, self.parameters, 0)
        layer.extract_features()
        layer.spot_bridge_infill()
        layer.make_polys_from_bridge_infill()
        layer.verify_infill_polys()
        layer.prepare_deletion()
        self.assertFalse(layer.export_this_line(3))
        self.assertTrue(layer.export_this_line(0))

    def test_get_file_stream_and_path(self):
        with patch("builtins.open", mock_open(read_data="data")) as mock_file:
            with patch("sys.argv", ["script.py", "test.gcode"]):
                file_stream, path = psp.get_file_stream_and_path()
                self.assertEqual(path, "test.gcode")
                self.assertEqual(file_stream.read(), "data")

    def test_main(self):
        with patch("builtins.open", mock_open(read_data="\n".join(self.gcode_lines))):
            with patch("sys.argv", ["script.py", "test.gcode"]):
                with patch("prusa_slicer_post_processing_script.get_file_stream_and_path", return_value=(MagicMock(), "test.gcode")):
                    with patch("prusa_slicer_post_processing_script.input", return_value=""):
                        psp.main(MagicMock(), "test.gcode", True)

    def test_detect_slicer_type_prusaslicer(self):
        gcode_lines = ["; generated by PrusaSlicer\n"]
        result = psp.detect_slicer_type(gcode_lines)
        self.assertEqual(result, "PrusaSlicer")

    def test_detect_slicer_type_orcaslicer(self):
        gcode_lines = ["; generated by OrcaSlicer\n"]
        result = psp.detect_slicer_type(gcode_lines)
        self.assertEqual(result, "OrcaSlicer")

    def test_read_settings_from_gcode2dict_prusaslicer(self):
        gcode_lines = [
            "; prusaslicer_config = begin\n",
            "nozzle_diameter = 0.4\n",
            "perimeter_extrusion_width = 0.45\n",
            "; prusaslicer_config = end\n"
        ]
        fallback_values_dict = {"Fallback_nozzle_diameter": 0.4, "Fallback_filament_diameter": 1.75}
        result = psp.read_settings_from_gcode2dict(gcode_lines, fallback_values_dict, "PrusaSlicer")
        self.assertEqual(result["nozzle_diameter"], 0.4)
        self.assertEqual(result["perimeter_extrusion_width"], 0.45)

    def test_read_settings_from_gcode2dict_orcaslicer(self):
        gcode_lines = [
            "; orcaslicer_config = begin\n",
            "nozzle_diameter = 0.4\n",
            "perimeter_extrusion_width = 0.45\n",
            "; orcaslicer_config = end\n"
        ]
        fallback_values_dict = {"Fallback_nozzle_diameter": 0.4, "Fallback_filament_diameter": 1.75}
        result = psp.read_settings_from_gcode2dict(gcode_lines, fallback_values_dict, "OrcaSlicer")
        self.assertEqual(result["nozzle_diameter"], 0.4)
        self.assertEqual(result["perimeter_extrusion_width"], 0.45)

    def test_check_for_necessary_settings_prusaslicer(self):
        gcode_setting_dict = {
            "use_relative_e_distances": True,
            "extrusion_width": 0.4,
            "perimeter_extrusion_width": 0.4,
            "solid_infill_extrusion_width": 0.4,
            "overhangs": True,
            "bridge_speed": 5,
            "infill_first": False,
            "external_perimeters_first": False,
            "avoid_crossing_perimeters": True
        }
        result = psp.check_for_necessary_settings(gcode_setting_dict, "PrusaSlicer")
        self.assertTrue(result)

    def test_check_for_necessary_settings_orcaslicer(self):
        gcode_setting_dict = {
            "use_relative_e_distances": True,
            "extrusion_width": 0.4,
            "perimeter_extrusion_width": 0.4,
            "solid_infill_extrusion_width": 0.4,
            "overhangs": True,
            "bridge_speed": 5,
            "infill_first": False,
            "external_perimeters_first": False,
            "avoid_crossing_perimeters": True
        }
        result = psp.check_for_necessary_settings(gcode_setting_dict, "OrcaSlicer")
        self.assertTrue(result)

if __name__ == "__main__":
    unittest.main()
