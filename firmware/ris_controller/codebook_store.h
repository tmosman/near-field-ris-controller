#pragma once

#include <stddef.h>
#include <stdint.h>

struct CodebookMeta {
  uint32_t magic;
  char name[64];
  uint32_t num_masks;
  uint32_t mask_bytes;
  uint32_t payload_crc32;
  uint32_t data_offset;
  uint32_t valid;
};

bool storeInit();
bool storeFlashAvailable();
bool storeUsingRam();
bool storeHasCodebook();
const CodebookMeta &storeMeta();

bool storeBeginWrite(const char *name, uint32_t num_masks, uint32_t mask_bytes, uint32_t expected_crc);
bool storeWriteChunk(const uint8_t *data, size_t len);
bool storeWriteComplete();
bool storeFinishWrite();
void storeAbortWrite();

bool storeReadMask(uint16_t index, uint8_t *out, uint16_t maskBytes);
bool storeReadPayloadAt(uint32_t offset, uint8_t *out, size_t len);
