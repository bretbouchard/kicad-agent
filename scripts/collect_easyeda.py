#!/usr/bin/env python3
"""Collect component knowledge from JLCPCB / EasyEDA into training data.

Searches JLCPCB for popular component categories, fetches full CAD data
(pin positions, packages, specs) from EasyEDA, and writes JSONL training
splits.

No GitHub token required. All APIs are anonymous.

Usage:
    python3 scripts/collect_easyeda.py --output-dir training_data_easyeda --max-components 5000

    # Search specific categories
    python3 scripts/collect_easyeda.py --categories "STM32" "ESP32" "NE555" "op-amp"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volta.crawler.easyeda_api import EasyEdaClient, JlcpcbComponent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_easyeda")

# Popular component categories for broad coverage
DEFAULT_CATEGORIES = [
    # Microcontrollers
    "STM32",
    "ESP32",
    "Arduino",
    "Raspberry Pi",
    "PIC microcontroller",
    "AVR microcontroller",
    "NRF52",
    "RP2040",
    "CH32V",
    "GD32",
    # Analog ICs
    "op-amp",
    "NE555",
    "comparator",
    "ADC",
    "DAC",
    "analog switch",
    "multiplexer",
    "voltage reference",
    "PLL",
    "VCO",
    # Power management
    "voltage regulator",
    "LDO regulator",
    "buck converter",
    "boost converter",
    "buck-boost converter",
    "battery charger",
    "battery fuel gauge",
    "power monitor",
    "LED driver",
    "motor driver",
    "H-bridge",
    "charge pump",
    # Transistors & diodes
    "mosfet N-channel",
    "mosfet P-channel",
    "transistor NPN",
    "transistor PNP",
    "diode schottky",
    "diode zener",
    "TVS diode",
    "rectifier diode",
    "IGBT",
    "JFET",
    # Passives
    "capacitor 100nF",
    "capacitor 10uF",
    "resistor 10k",
    "resistor 1k",
    "electrolytic capacitor",
    "inductor",
    "ferrite bead",
    "crystal oscillator",
    "ceramic resonator",
    # Connectors
    "USB-C",
    "USB connector",
    "HDMI connector",
    "RJ45 connector",
    "connector",
    "FPC connector",
    "board-to-board connector",
    "terminal block",
    "barrel jack",
    "SIM card holder",
    "SD card connector",
    # Communication
    "RS485",
    "CAN transceiver",
    "Ethernet PHY",
    "WiFi module",
    "Bluetooth module",
    "LoRa module",
    "NB-IoT module",
    "UART",
    "SPI",
    "I2C",
    "level shifter",
    "isolator",
    "optocoupler",
    # Memory & storage
    "EEPROM",
    "FLASH memory",
    "SRAM",
    "SDRAM",
    "DDR",
    "FRAM",
    # Sensors
    "temperature sensor",
    "humidity sensor",
    "pressure sensor",
    "accelerometer",
    "gyroscope",
    "IMU",
    "magnetometer",
    "light sensor",
    "proximity sensor",
    "gas sensor",
    "current sensor",
    "hall effect sensor",
    "microphone",
    # Audio
    "audio amplifier",
    "audio codec",
    "DAC audio",
    "ADC audio",
    "speaker amplifier",
    "headphone amplifier",
    # Displays
    "OLED display",
    "LCD driver",
    "LED matrix driver",
    "display controller",
    "segment driver",
    # Interface & logic
    "level translator",
    "logic gate",
    "flip-flop",
    "shift register",
    "counter",
    "decoder",
    "buffer",
    "timer",
    "watchdog",
    "reset IC",
    # Protection & filtering
    "ESD protection",
    "fuse",
    "circuit breaker",
    "EMI filter",
    "common mode choke",
    # Clock & timing
    "RTC",
    "clock generator",
    "clock buffer",
    "frequency synthesizer",
    # Prototyping
    "relay",
    "solid state relay",
    "switch",
    "button",
    "encoder",
    "potentiometer",
    "transformer",
    # RF
    "RF amplifier",
    "RF switch",
    "antenna",
    "BALUN",
    "filter SAW",
    "LNA",
    "mixer",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect component knowledge from JLCPCB/EasyEDA",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_data_easyeda"),
        help="Output directory for JSONL splits",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".easyeda_cache"),
        help="Cache directory for API responses",
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        default=None,
        help="Search categories (default: built-in list)",
    )
    parser.add_argument(
        "--max-components",
        type=int,
        default=100000,
        help="Maximum total components to collect",
    )
    parser.add_argument(
        "--pages-per-category",
        type=int,
        default=20,
        help="Max pages to fetch per search category",
    )
    args = parser.parse_args()

    categories = args.categories or DEFAULT_CATEGORIES
    client = EasyEdaClient(cache_dir=args.cache_dir)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Resume support: load previously collected samples ---
    checkpoint_path = output_dir / "checkpoint.jsonl"
    seen_lcsc: set[str] = set()
    all_samples: list[dict] = []
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            for line in f:
                try:
                    s = json.loads(line.strip())
                    all_samples.append(s)
                    seen_lcsc.add(s["lcsc"])
                except (json.JSONDecodeError, KeyError):
                    pass
        logger.info("Resumed from checkpoint: %d existing samples", len(all_samples))

    sample_id = len(all_samples)
    n_searched = 0
    n_fetched = 0
    n_failed = 0
    checkpoint_every = 50  # flush to disk every N new samples
    samples_since_checkpoint = 0

    consecutive_failures = 0
    max_consecutive_failures = 10  # skip category after this many in a row

    def flush_checkpoint() -> None:
        """Append new samples to checkpoint file."""
        if samples_since_checkpoint == 0:
            return
        start = len(all_samples) - samples_since_checkpoint
        with open(checkpoint_path, "a") as f:
            for s in all_samples[start:]:
                f.write(json.dumps(s) + "\n")
        logger.info("Checkpoint: %d total samples saved", len(all_samples))

    for cat_idx, keyword in enumerate(categories):
        if len(all_samples) >= args.max_components:
            logger.info("Reached max %d components, stopping", args.max_components)
            break

        logger.info(
            "Category %d/%d: '%s' (%d collected so far)",
            cat_idx + 1, len(categories), keyword, len(all_samples),
        )

        for page in range(1, args.pages_per_category + 1):
            components, total = client.search_jlcpcb(
                keyword=keyword,
                page=page,
                page_size=25,
            )
            n_searched += len(components)

            if not components:
                break

            for comp in components:
                if comp.lcsc in seen_lcsc:
                    continue
                seen_lcsc.add(comp.lcsc)

                # Fetch CAD data (pins, pads, footprint)
                cad = client.get_component_cad_data(comp.lcsc)

                # Track consecutive failures for rate-limit detection
                if cad is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.warning(
                            "%d consecutive failures, pausing 60s then skipping category '%s'",
                            consecutive_failures, keyword,
                        )
                        time.sleep(60)
                        consecutive_failures = 0
                        break
                else:
                    consecutive_failures = 0
                    if cad.pins or cad.pads:
                        logger.info(
                            "  %s: %d pins, %d pads, %s",
                            comp.lcsc, len(cad.pins), len(cad.pads), comp.name[:40],
                        )

                # Build training sample
                attrs_dict = {a["name"]: a["value"] for a in comp.attributes}

                sample = {
                    "sample_id": sample_id,
                    "source": "jlcpcb_easyeda",
                    "lcsc": comp.lcsc,
                    "name": comp.name,
                    "brand": comp.brand,
                    "package": comp.package,
                    "category": comp.category,
                    "stock": comp.stock,
                    "part_type": comp.part_type,
                    "price": comp.price,
                    "datasheet": comp.datasheet,
                    "pin_count": len(cad.pins) if cad else 0,
                    "pad_count": len(cad.pads) if cad else 0,
                    "pins": [
                        {
                            "number": p.pin_number,
                            "name": p.pin_name,
                            "x": p.pos_x,
                            "y": p.pos_y,
                            "type": p.pin_type,
                        }
                        for p in (cad.pins if cad else ())
                    ],
                    "pads": [
                        {
                            "number": p.pad_number,
                            "x": p.pos_x,
                            "y": p.pos_y,
                            "width": p.width,
                            "height": p.height,
                            "layer": p.layer,
                            "shape": p.shape,
                        }
                        for p in (cad.pads if cad else ())
                    ],
                    "attributes": attrs_dict,
                    "content_hash": hashlib.sha256(
                        f"{comp.lcsc}:{comp.name}:{comp.package}".encode()
                    ).hexdigest(),
                }

                all_samples.append(sample)
                sample_id += 1
                n_fetched += 1
                if cad is None:
                    n_failed += 1

                # Periodic checkpoint
                samples_since_checkpoint += 1
                if samples_since_checkpoint >= checkpoint_every:
                    flush_checkpoint()
                    samples_since_checkpoint = 0

                if len(all_samples) >= args.max_components:
                    break

                # Rate limit: 5s between CAD fetches to avoid 403 rate limiting
                time.sleep(5.0)

            if len(all_samples) >= args.max_components:
                break

            # Rate limit between pages
            time.sleep(1.0)

        logger.info(
            "  Category '%s' done: %d total components collected",
            keyword, len(all_samples),
        )
        flush_checkpoint()
        samples_since_checkpoint = 0

    # Final checkpoint flush
    flush_checkpoint()

    if not all_samples:
        logger.warning("No components collected")
        return 0

    # Dedup by LCSC (already done in memory, but double-check)
    seen: set[str] = set()
    unique: list[dict] = []
    for s in all_samples:
        if s["lcsc"] not in seen:
            seen.add(s["lcsc"])
            unique.append(s)

    # Write JSONL splits (final, deduped)
    output_dir = args.output_dir

    import random
    rng = random.Random(42)
    indices = list(range(len(unique)))
    rng.shuffle(indices)
    shuffled = [unique[i] for i in indices]

    train_end = int(len(shuffled) * 0.8)
    val_end = train_end + int(len(shuffled) * 0.1)

    for name, subset in [
        ("train", shuffled[:train_end]),
        ("val", shuffled[train_end:val_end]),
        ("test", shuffled[val_end:]),
    ]:
        path = output_dir / f"{name}.jsonl"
        with open(path, "w") as f:
            for s in subset:
                f.write(json.dumps(s) + "\n")

    # Stats (use .get() for backward compat with older checkpoint formats)
    with_pins = sum(1 for s in unique if s.get("pin_count", 0) > 0)
    with_pads = sum(1 for s in unique if s.get("pad_count", 0) > 0)
    total_pins = sum(s.get("pin_count", 0) for s in unique)
    total_pads = sum(s.get("pad_count", 0) for s in unique)
    categories_found = len(set(s.get("category", "unknown") for s in unique))
    brands_found = len(set(s.get("brand", "unknown") for s in unique))

    print(f"\n{'='*60}")
    print(f"EasyEDA collection complete: {len(unique)} components")
    print(f"  Categories searched: {len(categories)}")
    print(f"  JLCPCB results:      {n_searched}")
    print(f"  CAD data fetched:    {n_fetched}")
    print(f"  CAD fetch failed:    {n_failed}")
    print(f"  With pin data:       {with_pins} ({with_pins*100//max(len(unique),1)}%)")
    print(f"  With pad data:       {with_pads} ({with_pads*100//max(len(unique),1)}%)")
    print(f"  Total pins:          {total_pins:,}")
    print(f"  Total pads:          {total_pads:,}")
    print(f"  Unique categories:   {categories_found}")
    print(f"  Unique brands:       {brands_found}")
    print(f"  Splits:              {train_end} train / {val_end - train_end} val / {len(shuffled) - val_end} test")
    print(f"  Output:              {output_dir}/")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
