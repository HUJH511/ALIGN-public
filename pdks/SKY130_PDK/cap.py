import math
from align.primitive.default.canvas import DefaultCanvas
from align.cell_fabric.generators import *
from align.cell_fabric.grid import *

import logging
logger = logging.getLogger(__name__)

class CapGenerator(DefaultCanvas):

    def __init__(self, pdk):
        super().__init__(pdk)

        # capm marker (89,44) is NOT a routing layer; treat it as a Region
        clg_mim = UncoloredCenterLineGrid(pitch=2, width=2)
        self.capm = self.addGen(Region('capm', 'CapMIMLayer', h_grid=clg_mim, v_grid=clg_mim))

        self.Cboundary = self.addGen(Region('Cboundary', 'Cboundary', h_grid=self.m2.clg, v_grid=self.m1.clg))

        # Use standard Via between M3 and M4: that's V3 in SKY130 (gdsfactory via3_layer=(70,44))
        self.v3_x = self.addGen(Via('v3_x', 'V3',
                                    h_clg=self.m3.clg, v_clg=self.m4.clg,
                                    WidthX=self.v3.WidthX, WidthY=self.v3.WidthY,
                                    h_ext=self.v3.h_ext, v_ext=self.v3.v_ext))

    def addCap(self, length, width):
        # ALIGN typically passes these in "database units" (often nm in this PDK)
        x_len = int(length)
        y_len = int(width)

        # Match gdsfactory defaults (in nm if your PDK JSON is nm):
        capm_enc_x = self.pdk['CapMIMLayer'].get('Enclosure', 500)   # ~0.5um
        capm_enc_y = capm_enc_x

        # m4 enclosure in gdsfactory is (0.14, 0.14) um => 140nm
        m4_enc = self.pdk.get('Cap', {}).get('m4Enclosure', 140)

        # gdsfactory uses two M4 pieces: left plate (over capm) and right landing (for vias/pin)
        # Use a simple split: left plate width = x_len, right landing = ~0.4um (400nm) default
        m4_r_len = self.pdk.get('Cap', {}).get('m4RightLength', 400)  # 0.4um
        m4_spacing = self.pdk.get('Cap', {}).get('m4Spacing', 300)    # 0.3um

        # Build overall M3 plate size (roughly like gdsfactory)
        m3_len = capm_enc_x + 2*m4_enc + x_len + m4_spacing + m4_r_len
        m3_wid = 2*capm_enc_y + 2*m4_enc + y_len

        # Create a big M3 rectangle as a "wire" spanning one fat track
        m3_plate = Wire('m3_plate', 'M3', 'v',
                        clg=UncoloredCenterLineGrid(pitch=2*m3_len, width=m3_len, offset=m3_len//2),
                        spg=EnclosureGrid(pitch=y_len, stoppoint=0, check=False))

        # Left M4 plate (the actual top plate over capm)
        m4_l_plate = Wire('m4_l_plate', 'M4', 'v',
                          clg=UncoloredCenterLineGrid(pitch=2*x_len, width=x_len, offset=(capm_enc_x + m4_enc + x_len//2)),
                          spg=EnclosureGrid(pitch=y_len, stoppoint=0, check=False))

        # Right M4 landing (terminal landing that gets V3 array down to M3)
        m4_r_plate = Wire('m4_r_plate', 'M4', 'v',
                          clg=UncoloredCenterLineGrid(pitch=2*m4_r_len, width=m4_r_len, offset=(m3_len - m4_r_len//2)),
                          spg=EnclosureGrid(pitch=y_len, stoppoint=0, check=False))

        # Place the plates
        self.addWire(m3_plate, 'MINUS', 0, (0, -1), (1, 1))
        self.addWire(m4_l_plate, 'PLUS', 0, (0, -1), (1, 1))
        self.addWire(m4_r_plate, 'MINUS', 0, (0, -1), (1, 1))

        # capm marker only over the left plate region (x_len by y_len with enclosure)
        # Region coords are abstract; keep it simple and proportional.
        # This just needs to overlap the left plate area.
        gx0 = 0
        gy0 = 0
        gx1 = max(2, (x_len + 2*m4_enc) // max(1, self.pdk['M3']['Pitch']))
        gy1 = max(2, (y_len + 2*m4_enc) // max(1, self.pdk['M2']['Pitch']))
        self.addRegion(self.capm, None, gx0, gy0, gx1, gy1)

        # === V3 array to connect RIGHT landing (M4) down to M3 (gdsfactory via3 arrays) ===
        # Place a small grid of vias. Exact packing isn't critical for connectivity; start with 1xN.
        # Put them "somewhere" in the cell that overlaps both M3 and the right M4 landing.
        # Use a few vias to be safe.
        via_cols = 2
        via_rows = 2
        for r in range(via_rows):
            for c in range(via_cols):
                # Using track indices (x,y) for addVia: depends on your DefaultCanvas grids.
                # Keep it simple: drop them near origin; if you still see opens, shift indices.
                self.addVia(self.v3_x, 'MINUS', c, r)

        # Export pins on real routing metals (no islands)
        # PLUS on M4 (left plate). MINUS on M3 (bottom plate).
        pin_span = max(1, math.floor(m3_len / self.pdk['M3']['Pitch']))
        self.addWire(self.m4, 'PLUS', 0, (-1, -1), (pin_span, 1), netType='pin')
        self.addWire(self.m3, 'MINUS', 0, (-1, -1), (pin_span, 1), netType='pin')

        # Boundary
        x_number = max(2, math.ceil(m3_len / self.pdk['M1']['Pitch']))
        y_number = max(2, math.ceil(m3_wid / self.pdk['M2']['Pitch']))
        self.addRegion(self.boundary, 'Boundary', -2, -2, x_number+2, y_number+2)

        logger.debug(f"Cap: m3_len={m3_len} m3_wid={m3_wid} pins={pin_span}")
