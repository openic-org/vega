"""
RHD2164 ADC unit conversion.

Source: Intan_RHD2000_series_datasheet.pdf (on Manuel's machine, not tracked
in either repo — the RHD2164-specific datasheet has no Electrical
Characteristics table of its own, confirmed by search; the series datasheet
is the actual source, same document the 2026-08-24 session already used for
SPI timing), page 6, "Electrical Characteristics" table, symbol V_LSB.
Read from the rendered page image, not pdftotext — the 2026-08-24 session
found pdftotext mis-tabling numeric values in this document family.
Confirmed by Manuel 2026-08-27 (PLAN.md A.6.2, DECISION 1).
T_A = 25 degC, V_DD = 3.3V (datasheet table header; matches this board).

The on-chip ADC is shared and multiplexed across amplifier channels,
auxiliary inputs and the supply-voltage sensor, and the datasheet gives a
distinct step size for each — the LSB size depends on what's connected to
the ADC in a given conversion, not on which sampling slot it came from.
"""

# V_LSB, "referred to amplifier input" row. What CH0/CH1 (the two channels
# SET_CHANNELS selects and the app actually streams) are in normal operation.
AMPLIFIER_UV_PER_LSB = 0.195

# V_LSB, "referred to auxiliary ADC input" row. auxin1-3 (not currently
# sampled by this design — RHD_ADC_AUX1/2/3_EN are all 0 in rhd2164_defs.vh).
AUX_ADC_UV_PER_LSB = 37.4

# V_LSB, "referred to supply voltage sensor" row. Channel 48 (VDD/2 via
# on-chip divider) — matches PLAN.md A.1.1f's independently-derived
# "VDD = 0.0000748 x result" note exactly (0.0000748 V = 74.8 uV), which
# cross-checks this constant against a second source already in the plan.
SUPPLY_SENSE_UV_PER_LSB = 74.8


def counts_to_uv(counts, uv_per_lsb: float = AMPLIFIER_UV_PER_LSB):
    """Convert raw signed ADC counts to microvolts.

    Defaults to the amplifier-referred step size, since CH0/CH1 (the two
    streamed channels) are amplifier channels in normal operation. Pass
    SUPPLY_SENSE_UV_PER_LSB or AUX_ADC_UV_PER_LSB explicitly when converting
    a non-amplifier channel (e.g. the A.1.1f VDD-sense reading on channel 48).
    """
    return counts * uv_per_lsb
