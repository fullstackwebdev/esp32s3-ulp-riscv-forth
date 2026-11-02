#!/usr/bin/env python3
"""Duty-cycle and battery arithmetic for the ULP LoRa node, from measured numbers only.

    python3 probe/lora/power_budget.py

Every input that was MEASURED on the board is marked; every input that is a datasheet-typical figure is marked as such,
because a power budget built from unlabelled numbers is how "months on a battery" becomes a marketing sentence. The
measurements come from probe/lora (docs/28 §6): ULP awake window per warm transmit, SPI clock, packet air time.

What is NOT measured here: current. There is no meter on this bench, so the mA figures are the SX1262 datasheet's
typical values at 14 dBm with the DC-DC converter, plus the S3's documented deep-sleep current. They are labelled.
"""
import argparse

# ---- measured on the Heltec V3 (probe/lora console output, 2026-11-01) -------------------------------------------
ULP_AWAKE_MS = 195.8      # measured: main core timed the ULP's awake window at 200 us resolution
AIR_MS = 185.34           # derived: Tsym 4.096 ms, preamble 50.18 ms, 33 payload symbols 135.17 ms
SPI_CYCLES_PER_BYTE = 971 # measured: ULP cycle counter, one 16-byte transaction
ULP_CLOCK_HZ = 17.55e6    # measured: 175 503 cycles per 10 ms delay

# ---- datasheet-typical, NOT measured here -----------------------------------------------------------------------
I_TX_14DBM_MA = 45.0      # SX1262 +14 dBm with DC-DC, typical
I_STANDBY_MA = 0.0006     # SX1262 warm sleep (configuration retained), typical ~0.6 uA
I_ULP_MA = 5.0            # ESP32-S3 ULP-RISC-V plus RTC domain while the ULP is running, rough
I_DEEPSLEEP_UA = 10.0     # ESP32-S3 deep sleep, RTC slow memory retained, typical
V = 3.7                   # Li-ion single cell nominal


def per_hour(period_s):
    """Charge used per hour, in mAh, for one transmission every period_s seconds."""
    packets_per_hour = 3600.0 / period_s
    tx_charge = I_TX_14DBM_MA * (AIR_MS / 1000.0)                 # the radio is the one drawing real current
    ulp_charge = I_ULP_MA * ((ULP_AWAKE_MS - AIR_MS) / 1000.0)     # the ULP's own compute inside that window
    per_packet = (tx_charge + ulp_charge) / 3600.0                # mAs -> mAh
    sleep_h = max(period_s - ULP_AWAKE_MS / 1000.0, 0.0) / 3600.0
    sleep_charge = (I_STANDBY_MA + I_DEEPSLEEP_UA / 1000.0) * sleep_h
    return packets_per_hour * per_packet + packets_per_hour * sleep_charge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell-mah", type=float, default=2000.0, help="usable capacity, default a 2000 mAh 18650")
    args = ap.parse_args()

    print("measured : ULP awake %.1f ms per transmit, of which %.1f ms is the packet on air (%.0f %%)"
          % (ULP_AWAKE_MS, AIR_MS, 100.0 * AIR_MS / ULP_AWAKE_MS))
    # GUARDRAIL: derive the rate ONCE, in bytes/second, then convert with the factors spelled out. This same unit slip
    # has now happened four times in this project (1000x on the ULP SCK column, on the app-store hop timing, here again):
    # bytes/s is not kHz, and kHz is 8x bytes/s for a serial line. One named value plus explicit conversions, never a
    # ratio of two rates written inline.
    bytes_per_s = ULP_CLOCK_HZ / SPI_CYCLES_PER_BYTE
    us_per_byte = 1e6 / bytes_per_s
    sck_hz = bytes_per_s * 8.0
    print("measured : SPI %.0f cycles/byte at %.2f MHz -> %.1f kB/s -> %.1f kHz SCK, %.1f us/byte"
          % (SPI_CYCLES_PER_BYTE, ULP_CLOCK_HZ / 1e6, bytes_per_s / 1000.0, sck_hz / 1000.0, us_per_byte))
    print("datasheet: %.0f mA TX @14 dBm, %.1f uA radio warm sleep, ~%.0f uA CPU deep sleep, %.0f mA ULP running"
          % (I_TX_14DBM_MA, I_STANDBY_MA * 1000, I_DEEPSLEEP_UA, I_ULP_MA))
    print()
    print("  period   packets/day   average draw    %s cell lasts" % args.cell_mah)
    for period_s in (5, 10, 30, 60, 300, 900, 3600):
        mah_per_h = per_hour(period_s)
        avg_ma = mah_per_h
        days = args.cell_mah / mah_per_h / 24.0 if mah_per_h > 0 else float("inf")
        span = ("%.1f days" % days) if days < 400 else ("%.1f years" % (days / 365.0))
        print("  %5d s   %11.0f   %10.3f mA   %s" % (period_s, 86400.0 / period_s, avg_ma, span))
    print()
    print("reading: the ULP's own compute is %.1f ms of a %.1f ms window - %.0f %% - so the radio, not the"
          % (ULP_AWAKE_MS - AIR_MS, ULP_AWAKE_MS, 100.0 * (ULP_AWAKE_MS - AIR_MS) / ULP_AWAKE_MS))
    print("         interpreter, sets the budget. The lever that buys months is the PERIOD, and after that the")
    print("         air time (spreading factor, payload length), not the SPI clock.")


if __name__ == "__main__":
    main()
