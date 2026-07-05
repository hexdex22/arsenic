"""Live GPS data display app: reads NMEA 0183 from a GPS chip and
continuously displays every field it reports (web dashboard + terminal).

Pure standard library; optionally uses pyserial for baud-rate control.
"""

__version__ = "1.0"
