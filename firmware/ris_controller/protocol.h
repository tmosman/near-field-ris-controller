#pragma once

#include <stdint.h>

void protocolInit();
void protocolPoll();
void protocolApplyIndex(uint16_t index);
