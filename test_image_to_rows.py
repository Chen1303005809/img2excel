from __future__ import annotations

import unittest
from pathlib import Path

from image_to_rows import extract


ROOT = Path(__file__).parent


class ImageToRowsRegressionTests(unittest.TestCase):
    def test_table4_keeps_all_colored_sections_and_footer_text(self) -> None:
        data = extract(ROOT / "example_pics" / "表4期权限仓20260609.png")

        expected_labels = [
            "大连商品交易所",
            "郑州商品交易所",
            "上海期货交易所",
            "上海国际能源交易中心",
            "中国金融期货交易所",
            "广州期货交易所",
        ]
        self.assertEqual([section["label"] for section in data["sections"]], expected_labels)
        self.assertEqual(
            [(len(section["cells"]), len(section["x_edges"]) - 1) for section in data["sections"]],
            [(11, 2), (17, 3), (22, 3), (7, 4), (4, 3), (4, 2)],
        )
        notes = "\n".join(note["text"] for note in data.get("colored_notes", []))
        self.assertIn("分别计算", notes)
        footer = "\n".join(note["text"] for note in data.get("footer_notes", []))
        self.assertIn("400-700-7878", footer)

    def test_same_table6_template_keeps_the_same_column_structure(self) -> None:
        signatures = []
        for name in ("表6异常交易20260415.png", "表6异常交易20260714.png"):
            data = extract(ROOT / "example_pics" / name)
            signatures.append([len(section["x_edges"]) - 1 for section in data["sections"]])
            self.assertIn("套利、套保是否豁免", data["sections"][0]["cells"][0][4].replace("\n", ""))

        self.assertEqual(signatures[0], signatures[1])


if __name__ == "__main__":
    unittest.main()
