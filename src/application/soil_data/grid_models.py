"""
SoilGrids rasters (ISRIC, 1 km) loaded into the database as georeferenced tiles.

A `soilgrids_grids` row describes one regular lat/lon grid (its upper-left corner, pixel size and shape); its
`soilgrids_tiles` hold one property at one depth, cut into TILE x TILE blocks of int16 (zlib-compressed). A point is
turned into a pixel with the grid's geotransform, the tile that holds it is read by primary key, and the value comes
out of the block: no external service, no PostGIS raster, a few milliseconds. Tiles that are all no-data are not stored.
Filled by `python -m src.scripts.import_soilgrids`; read by `soilgrids_repository.py`.
"""
from sqlalchemy import Column, Float, ForeignKey, Integer, LargeBinary, String

from src.shared.database import Base


class SoilGridsGrid(Base):
    __tablename__ = "soilgrids_grids"

    grid = Column(String(40), primary_key=True)  # e.g. "mexico", "argentina"
    min_lon = Column(Float, nullable=False)  # west edge
    max_lat = Column(Float, nullable=False)  # north edge
    res_lon = Column(Float, nullable=False)  # degrees per pixel
    res_lat = Column(Float, nullable=False)
    width = Column(Integer, nullable=False)  # pixels
    height = Column(Integer, nullable=False)
    tile_size = Column(Integer, nullable=False)
    resolution_m = Column(Integer, nullable=False)  # nominal, for the answer's caveat


class SoilGridsTile(Base):
    __tablename__ = "soilgrids_tiles"

    grid = Column(String(40), ForeignKey("soilgrids_grids.grid", ondelete="CASCADE"), primary_key=True)
    prop = Column(String(12), primary_key=True)  # phh2o | soc | nitrogen | cec
    depth = Column(String(10), primary_key=True)  # 0-5cm | 5-15cm | 15-30cm ...
    tx = Column(Integer, primary_key=True)  # tile column
    ty = Column(Integer, primary_key=True)  # tile row (from the north)
    data = Column(LargeBinary, nullable=False)
