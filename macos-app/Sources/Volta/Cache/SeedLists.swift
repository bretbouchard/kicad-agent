//
//  SeedLists.swift
//  Volta
//
//  Phase 2 / Task 5 — Pre-Seeding
//
//  Curated part lists for cache pre-seeding. These cover the most common
//  components a PCB designer would search for. Pre-seeding ensures instant
//  results for popular parts on first launch.
//

import Foundation

/// Curated seed lists for pre-seeding the component cache.
enum SeedLists {

    // MARK: - MCUs (Top ~80)

    /// Top MCUs across major families. These are the parts most likely
    /// searched in the first session.
    static let mcus: [String] = [
        // STM32
        "STM32F103C8T6", "STM32F103RET6", "STM32F407VGT6", "STM32F411RET6",
        "STM32F401RET6", "STM32G0B1RET6", "STM32L432KC", "STM32H743VI",
        // ESP32
        "ESP32-WROOM-32", "ESP32-WROOM-32E", "ESP32-S3-WROOM-1", "ESP32-C3-32S",
        "ESP8266EX", "ESP-WROOM-02",
        // nRF
        "nRF52840", "nRF52832", "nRF51822",
        // RP2040
        "RP2040",
        // ATmega/ATtiny
        "ATmega328P-AU", "ATmega328P-PU", "ATmega2560-16AU", "ATmega32U4-AU",
        "ATtiny85", "ATtiny84", "ATtiny88",
        // PIC
        "PIC16F877A", "PIC18F4550", "PIC32MX320F128H",
        // SAMD
        "ATSAMD21G18", "ATSAMD21E18", "ATSAME54",
    ]

    // MARK: - Power ICs (Top ~60)

    static let powerICs: [String] = [
        // Linear regulators
        "LM7805", "LM7809", "LM7812", "LM7905", "LM317", "LM337",
        "AMS1117-3.3", "AMS1117-5.0", "AMS1117-1.8",
        "RT9193-33", "ME6211",
        // Switching regulators
        "LM2596", "LM2576", "MP1584", "MP2307", "TPS5430",
        "TPS63020", "TPS61023", "XL4015", "XL6009",
        "MT3608", "LM2675",
        // Battery charging
        "TP4056", "MCP73831", "BQ24075", "CN3791",
        "MAX1555", "LTC4054",
        // Power management
        "TPS2596", "LTC4365", "MAX4376",
    ]

    // MARK: - Connectors (Top ~40)

    static let connectors: [String] = [
        // USB
        "USB4105", "USB-C-16P", "USB4085",   // USB-C receptacles
        "USB-B-MICRO", "USB-A-S",             // Micro/B/A
        // Headers
        "HDR-2.54-2x20", "HDR-2.54-1x40", "HDR-2.54-1x2",
        "HDR-1.27-2x5",
        // HDMI
        "HDMI-AM-1001", "HDMI-A-S",
        // Board-to-board
        "M.2-KEY-M", "M.2-KEY-B",
        "DF40C-100DS-0.4V",
        // Audio
        "PJ-320D", "PJ-3240",                 // 3.5mm jacks
        // Terminal blocks
        "TB-2P-5.0", "TB-3P-5.0", "TB-4P-3.81",
        // FFC
        "FH12-24S-0.5SH", "FH12-40S-0.5SH",
    ]

    // MARK: - Passives (E12/E24 sample values)

    /// Representative resistor/capacitor values from E12 series.
    /// Not every value — just common ones a designer would look up.
    static let passives: [String] = [
        // Resistors (0603/0402 common values)
        "100R 0603", "220R 0603", "470R 0603", "1K 0603", "2K2 0603",
        "4K7 0603", "10K 0603", "22K 0603", "47K 0603", "100K 0603",
        "220K 0603", "470K 0603", "1M 0603",
        "100R 0402", "10K 0402", "100K 0402", "4K7 0402",
        // Capacitors (MLCC common values)
        "100nF 0603", "1uF 0603", "10uF 0805", "100uF 1206",
        "22pF 0603", "10nF 0603", "4.7uF 0805", "22uF 1206",
        "100nF 0402", "1uF 0402", "10uF 0603",
        // Tantalum
        "10uF Tantalum", "100uF Tantalum",
    ]

    // MARK: - Common ICs (Op-amps, logic, interface)

    static let commonICs: [String] = [
        // Op-amps
        "LM358", "LM324", "TL072", "TL084", "NE5532", "OPA2134",
        "MCP6001", "MCP6002", "AD823",
        // Comparators
        "LM393", "LM339",
        // Timers
        "NE555", "TLC555",
        // Logic
        "74HC00", "74HC02", "74HC04", "74HC08", "74HC14", "74HC32",
        "74HC138", "74HC595", "74HC165", "CD4017",
        // Interface
        "MAX3232", "MAX485", "SN65HVD230", "MCP2515",
        "FT232RL", "CP2102", "CH340G",
        // Sensors
        "BMP280", "BME280", "MPU6050", "DS18B20", "DHT22",
        // EEPROM
        "24C02", "24C256", "W25Q128",
    ]

    // MARK: - All Parts

    /// All seed parts combined.
    static let all: [String] = mcus + powerICs + connectors + passives + commonICs

    /// Total count for progress display.
    static var totalCount: Int { all.count }
}
