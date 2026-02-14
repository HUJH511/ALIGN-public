import math
import logging

from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import Wire, Via, Region
from align.cell_fabric.grid import UncoloredCenterLineGrid, EnclosureGrid

logger = logging.getLogger(__name__)


class CapGenerator(DefaultCanvas):
    """
    SKY130 MIMCAP generator for ALIGN.

    Key fixes vs your original cap.py:
      1) CapMIMContact is instantiated as a Via (connectivity object), NOT a Region (just geometry).
      2) The CapMIMContact via is dropped exactly at the intersection of:
            - CapMIMLayer MINUS plate (track 0)
            - M5 MINUS strap (track 0)
         so LVS/graph connectivity sees a real connection.
      3) Backward-compatible with PDKs that only provide 'Enclosure' (no Venc* fields).
    """

    def __init__(self, pdk):
        super().__init__(pdk)

        # CapMIMLayer wire generator (used for MINUS plate)
        self.m3n = self.addGen(
            Wire(
                "m3n",
                "CapMIMLayer",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=self.pdk["M3"]["Pitch"],
                    width=self.pdk["M3"]["Width"],
                ),
                spg=EnclosureGrid(
                    pitch=self.pdk["M2"]["Pitch"],
                    stoppoint=self.pdk["V2"]["VencA_H"] + self.pdk["M2"]["Width"] // 2,
                    check=False,
                ),
            )
        )

        # M5 strap that we use to bring out one plate
        self.m5_offset = (
            self.pdk["CapMIMLayer"]["Enclosure"]
            + self.pdk["CapMIMContact"].get("Enclosure", 0)
            + self.pdk["CapMIMContact"]["WidthX"] // 2
        )

        self.m5n = self.addGen(
            Wire(
                "m5n",
                "M5",
                "v",
                clg=UncoloredCenterLineGrid(
                    pitch=2 * self.pdk["Cap"]["m5Width"],
                    width=self.pdk["Cap"]["m5Width"],
                    offset=self.m5_offset,
                ),
                spg=EnclosureGrid(
                    pitch=self.pdk["M4"]["Pitch"] // 2,
                    stoppoint=self.pdk["CapMIMContact"].get("Enclosure", 0),
                    offset=0,
                    check=False,
                ),
            )
        )

        # Boundary marker (unchanged)
        self.Cboundary = self.addGen(
            Region("Cboundary", "Cboundary", h_grid=self.m2.clg, v_grid=self.m1.clg)
        )

        # ---- FIX: CapMIMContact must be a VIA (connectivity), not a Region ----
        cmc = self.pdk["CapMIMContact"]
        # Prefer explicit via enclosures if your layers.json provides them; fall back to 'Enclosure'
        h_ext = cmc.get("VencA_L", cmc.get("Enclosure", 0))
        v_ext = cmc.get("VencA_H", cmc.get("Enclosure", 0))

        self.mimc = self.addGen(
            Via(
                "mimc",
                "CapMIMContact",
                h_clg=self.m3n.clg,   # CapMIMLayer grid
                v_clg=self.m5n.clg,   # M5 grid
                WidthX=cmc["WidthX"],
                WidthY=cmc["WidthY"],
                h_ext=h_ext,
                v_ext=v_ext,
            )
        )

        # Existing via between M4 and M5 (unchanged)
        self.v4_x = self.addGen(
            Via(
                "v4_x",
                "V4",
                h_clg=self.m4.clg,
                v_clg=self.m5n.clg,
                WidthX=self.v4.WidthX,
                WidthY=self.v4.WidthY,
                h_ext=self.v4.h_ext,
                v_ext=self.v4.v_ext,
            )
        )

    def addCap(self, length, width):
        x_length = int(length)
        y_length = int(width)

        m1_p = self.pdk["M1"]["Pitch"]
        m2_p = self.pdk["M2"]["Pitch"]

        m4n_xwidth = x_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]
        m4n_ywidth = y_length + 2 * self.pdk["CapMIMLayer"]["Enclosure"]

        # NOTE: keeping your original plate construction logic intact
        # (the main functional fix here is the CapMIMContact connectivity via).
        m4n = Wire(
            "m4n",
            "M4",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=2 * m4n_xwidth, width=m4n_xwidth, offset=m4n_xwidth // 2
            ),
            spg=EnclosureGrid(
                pitch=y_length,
                stoppoint=self.pdk["CapMIMLayer"]["Enclosure"],
                check=False,
            ),
        )

        m4n_plate = Wire(
            "m4n_plate",
            "M4",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=m4n_xwidth - self.pdk["Cap"]["m4Width"] // 2,
                width=self.pdk["Cap"]["m4Width"],
                offset=0,
            ),
            spg=EnclosureGrid(
                pitch=self.pdk["M4"]["Pitch"],
                stoppoint=0,
                offset=-self.pdk["M4"]["Width"] // 4,
                check=False,
            ),
        )

        mimcap = Wire(
            "mim",
            "CapMIMLayer",
            "v",
            clg=UncoloredCenterLineGrid(
                pitch=2 * x_length,
                width=x_length,
                offset=x_length // 2 + self.pdk["CapMIMLayer"]["Enclosure"],
            ),
            spg=EnclosureGrid(pitch=y_length, stoppoint=0, check=False),
        )

        x_number = math.ceil(m4n_xwidth / m1_p)
        y_number_m4 = math.ceil(
            (
                y_length
                + self.pdk["CapMIMLayer"]["Enclosure"]
                + 0.5 * self.pdk["M4"]["Width"]
            )
            / self.pdk["M4"]["Pitch"]
        )
        y_number = math.ceil((y_number_m4 * self.pdk["M4"]["Pitch"]) / m2_p)

        logger.debug(f"Number of wires {x_number} {y_number}")

        # Plates / straps
        self.addWire(m4n, "MINUS", 0, (0, -1), (1, 1))
        self.addWire(m4n_plate, "PLUS", 1, (y_number_m4 - 1 - 1, -1), (y_number_m4, 1))
        self.addWire(mimcap, "MINUS", 0, (0, -1), (1, 1))

        # M5 strap for MINUS
        self.addWire(self.m5n, "MINUS", 0, (-3, 1), (1, 1))

        # Connect M4 ↔ M5 (your existing)
        self.addVia(self.v4_x, "MINUS", 0, -1)

        # ---- FIX: Connect CapMIMLayer ↔ M5 using a real VIA, aligned to tracks ----
        # Track 0 on CapMIMLayer (MINUS plate) and track 0 on M5 (MINUS strap).
        self.addVia(self.mimc, "MINUS", 0, 0)

        # Pins on M4 (unchanged)
        gridx2 = math.floor(m4n_xwidth / self.pdk["M3"]["Pitch"])
        self.addWire(self.m4, "PLUS", y_number_m4, (-1, -1), (gridx2, 1), netType="pin")
        self.addWire(self.m4, "MINUS", -1, (-1, -1), (gridx2, 1), netType="pin")

        # Boundary (unchanged)
        self.addRegion(self.boundary, "Boundary", -2, -6, x_number + 1, y_number + 3)

        logger.debug(
            f"Computed Boundary: {self.terminals[-1]} "
            f"{self.terminals[-1]['rect'][2]} {self.terminals[-1]['rect'][2] % 80}"
        )
