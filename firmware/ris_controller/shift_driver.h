#pragma once

#include <stdint.h>

void shiftInit();
void shiftClear();
void shiftOutputFromBuffer(const uint8_t *maskData, uint16_t maskBytes);
