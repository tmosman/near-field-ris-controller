#pragma once

#include <stdint.h>

// RIS shift-register hardware mapping (Teensy 4.x) — matches Imaging_Empty.ino
static const int DATA_PIN_COUNT = 20;
static const int DATA_PINS[DATA_PIN_COUNT] = {
    23, 22, 21, 20, 19, 18, 17, 16, 15, 14,
    41, 40, 39, 38, 36, 35, 2, 3, 25, 26
};

static const int SERIAL_CLOCK_PIN_M = 6;  // DO NOT use SerialFlash (claims this pin)
static const int SERIAL_CLOCK_PIN_T = 7;
static const int REGISTER_CLOCK_PIN_T = 8;

static const uint16_t DEFAULT_MASK_BYTES = 1280;
static const uint16_t MAX_MASK_BYTES = 1280;
// Legacy outputBits reads 20 bytes past mask end (next mask head in PROGMEM).
static const uint16_t LEGACY_MASK_TAIL_BYTES = 20;
static const uint16_t MAX_MASK_SCRATCH_BYTES = MAX_MASK_BYTES + LEGACY_MASK_TAIL_BYTES;
static const uint16_t MAX_MASKS = 1024;

static const int COMMAND_BUFFER_SIZE = 128;

static const uint32_t META_MAGIC = 0x52495331;  // 'RIS1'
