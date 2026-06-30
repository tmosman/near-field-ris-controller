#include "codebook_store.h"
#include "config.h"

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

// Pin 6 is SERIAL_CLOCK_PIN_M (shift clock). Do NOT call SerialFlash.begin() — it
// reconfigures pin 6 for SPI flash and breaks the RIS shift chain even when init fails.

static CodebookMeta activeMeta;
static bool writeActive = false;
static uint32_t writeOffset = 0;
static uint32_t writeRemaining = 0;
static uint32_t writeCrc = 0xFFFFFFFFUL;

static uint8_t *ramPayload = nullptr;
static uint32_t ramPayloadSize = 0;
static bool ramValid = false;

static uint32_t crc32Update(uint32_t crc, uint8_t byte) {
  crc ^= byte;
  for (int i = 0; i < 8; i++) {
    uint32_t mask = -(crc & 1UL);
    crc = (crc >> 1) ^ (0xEDB88320UL & mask);
  }
  return crc;
}

static uint32_t crc32Finalize(uint32_t crc) {
  return crc ^ 0xFFFFFFFFUL;
}

static void clearMeta(CodebookMeta &meta) {
  memset(&meta, 0, sizeof(meta));
}

static void freeRamPayload() {
  if (ramPayload != nullptr) {
    free(ramPayload);
    ramPayload = nullptr;
  }
  ramPayloadSize = 0;
}

static bool ensureRamPayload(uint32_t size) {
  if (size == 0) {
    return false;
  }
  if (ramPayload != nullptr && ramPayloadSize >= size) {
    return true;
  }
  freeRamPayload();
  ramPayload = (uint8_t *)malloc(size);
  if (ramPayload == nullptr) {
    return false;
  }
  ramPayloadSize = size;
  return true;
}

static bool loadMeta() {
  clearMeta(activeMeta);
  if (!ramValid || ramPayload == nullptr || activeMeta.valid != 1) {
    return false;
  }
  return activeMeta.magic == META_MAGIC;
}

static void writePayload(uint32_t offset, const uint8_t *data, size_t len) {
  if (ramPayload == nullptr || offset + len > ramPayloadSize) {
    return;
  }
  memcpy(ramPayload + offset, data, len);
}

static void readPayload(uint32_t offset, uint8_t *data, size_t len) {
  if (ramPayload == nullptr || offset + len > ramPayloadSize) {
    memset(data, 0, len);
    return;
  }
  memcpy(data, ramPayload + offset, len);
}

bool storeFlashAvailable() {
  return false;
}

bool storeUsingRam() {
  return true;
}

bool storeInit() {
  return loadMeta();
}

bool storeHasCodebook() {
  return activeMeta.valid == 1 && activeMeta.num_masks > 0;
}

const CodebookMeta &storeMeta() {
  return activeMeta;
}

bool storeBeginWrite(const char *name, uint32_t num_masks, uint32_t mask_bytes, uint32_t expected_crc) {
  if (num_masks == 0 || num_masks > MAX_MASKS || mask_bytes == 0 || mask_bytes > MAX_MASK_BYTES) {
    return false;
  }

  const uint32_t payloadSize = num_masks * mask_bytes;
  if (!ensureRamPayload(payloadSize)) {
    return false;
  }

  clearMeta(activeMeta);
  activeMeta.magic = META_MAGIC;
  strncpy(activeMeta.name, name, sizeof(activeMeta.name) - 1);
  activeMeta.num_masks = num_masks;
  activeMeta.mask_bytes = mask_bytes;
  activeMeta.payload_crc32 = expected_crc;
  activeMeta.data_offset = 0;
  activeMeta.valid = 0;

  writeActive = true;
  writeOffset = 0;
  writeRemaining = payloadSize;
  writeCrc = 0xFFFFFFFFUL;
  return true;
}

bool storeWriteChunk(const uint8_t *data, size_t len) {
  if (!writeActive || len == 0) {
    return false;
  }
  if (len > writeRemaining) {
    len = writeRemaining;
  }

  writePayload(writeOffset, data, len);

  for (size_t i = 0; i < len; i++) {
    writeCrc = crc32Update(writeCrc, data[i]);
  }

  writeOffset += len;
  writeRemaining -= len;
  return true;
}

bool storeWriteComplete() {
  return writeActive && writeRemaining == 0;
}

bool storeFinishWrite() {
  if (!storeWriteComplete()) {
    return false;
  }

  uint32_t finalCrc = crc32Finalize(writeCrc);
  if (finalCrc != activeMeta.payload_crc32) {
    writeActive = false;
    return false;
  }

  activeMeta.valid = 1;
  writeActive = false;
  ramValid = true;
  return true;
}

void storeAbortWrite() {
  writeActive = false;
  writeOffset = 0;
  writeRemaining = 0;
  writeCrc = 0xFFFFFFFFUL;
}

bool storeReadMask(uint16_t index, uint8_t *out, uint16_t maskBytes) {
  if (!storeHasCodebook() || index >= activeMeta.num_masks || maskBytes < activeMeta.mask_bytes) {
    return false;
  }

  uint32_t offset = (uint32_t)index * activeMeta.mask_bytes;
  readPayload(offset, out, activeMeta.mask_bytes);
  return true;
}

bool storeReadPayloadAt(uint32_t offset, uint8_t *out, size_t len) {
  if (!storeHasCodebook() || out == nullptr || len == 0) {
    return false;
  }
  const uint32_t payloadSize = activeMeta.num_masks * activeMeta.mask_bytes;
  if (offset >= payloadSize || offset + len > payloadSize) {
    return false;
  }
  readPayload(offset, out, len);
  return true;
}
