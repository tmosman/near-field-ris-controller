#include "protocol.h"
#include "codebook_store.h"
#include "config.h"
#include "shift_driver.h"

#include <Arduino.h>
#include <string.h>
#include <stdlib.h>

enum ParserState {
  STATE_LINE,
  STATE_BINARY_UPLOAD
};

static ParserState parserState = STATE_LINE;
static char lineBuffer[COMMAND_BUFFER_SIZE];
static size_t lineLength = 0;

static uint8_t uploadBuffer[512];
static uint8_t maskScratch[MAX_MASK_SCRATCH_BYTES];

static void reply(const char *msg) {
  Serial.println(msg);
  Serial.flush();
}

static bool loadMaskForLegacyShift(uint16_t index) {
  if (!storeHasCodebook() || index >= storeMeta().num_masks) {
    return false;
  }
  const CodebookMeta &meta = storeMeta();
  if (!storeReadMask(index, maskScratch, MAX_MASK_BYTES)) {
    return false;
  }
  const uint32_t tailOffset = (uint32_t)index * meta.mask_bytes + meta.mask_bytes;
  if (!storeReadPayloadAt(tailOffset, maskScratch + meta.mask_bytes, LEGACY_MASK_TAIL_BYTES)) {
    memset(maskScratch + meta.mask_bytes, 0, LEGACY_MASK_TAIL_BYTES);
  }
  return true;
}

static bool parseApplyIndex(const char *text, uint16_t *outIndex) {
  long value = atol(text);
  if (value < 0 || value > 65535) {
    return false;
  }
  *outIndex = (uint16_t)value;
  return true;
}

static void handleApply(uint16_t index) {
  if (!storeHasCodebook()) {
    reply("ERR NO_CODEBOOK");
    return;
  }
  const CodebookMeta &meta = storeMeta();
  if (index >= meta.num_masks) {
    reply("ERR INDEX_OUT_OF_RANGE");
    return;
  }
  if (!loadMaskForLegacyShift(index)) {
    reply("ERR APPLY_READ");
    return;
  }

  reply("OK APPLY_QUEUED");
  shiftOutputFromBuffer(maskScratch, meta.mask_bytes);

  Serial.print("OK APPLIED ");
  Serial.println(index);
  Serial.flush();
}

static void handleStatus() {
  if (!storeHasCodebook()) {
    Serial.print("OK store=empty masks=0 mask_bytes=0 name=none backend=ram");
    Serial.println();
    return;
  }
  const CodebookMeta &meta = storeMeta();
  Serial.print("OK store=ram masks=");
  Serial.print(meta.num_masks);
  Serial.print(" mask_bytes=");
  Serial.print(meta.mask_bytes);
  Serial.print(" name=");
  Serial.print(meta.name);
  Serial.print(" crc=");
  Serial.println(meta.payload_crc32, HEX);
}

static void handleCodebookBegin(char *args) {
  char *name = strtok(args, " ");
  char *numMasksStr = strtok(nullptr, " ");
  char *maskBytesStr = strtok(nullptr, " ");
  char *crcStr = strtok(nullptr, " ");

  if (!name || !numMasksStr || !maskBytesStr || !crcStr) {
    reply("ERR CODEBOOK_BEGIN_ARGS");
    return;
  }

  uint32_t num_masks = (uint32_t)strtoul(numMasksStr, nullptr, 10);
  uint32_t mask_bytes = (uint32_t)strtoul(maskBytesStr, nullptr, 10);
  uint32_t crc = (uint32_t)strtoul(crcStr, nullptr, 16);

  if (!storeBeginWrite(name, num_masks, mask_bytes, crc)) {
    reply("ERR CODEBOOK_BEGIN_REJECTED");
    return;
  }

  parserState = STATE_BINARY_UPLOAD;
  reply("READY");
}

static void handleLine(char *line) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  if (*line == '\0') {
    return;
  }

  if (strcmp(line, "PING") == 0) {
    reply("PONG");
    return;
  }
  if (strcmp(line, "STATUS") == 0) {
    handleStatus();
    return;
  }
  if (strcmp(line, "CLEAR") == 0) {
    shiftClear();
    reply("OK CLEARED");
    return;
  }
  if (strcmp(line, "CODEBOOK_END") == 0) {
    reply("ERR NOT_UPLOADING");
    return;
  }
  if (strcmp(line, "ABORT") == 0) {
    storeAbortWrite();
    parserState = STATE_LINE;
    reply("OK ABORTED");
    return;
  }

  if (strncmp(line, "APPLY ", 6) == 0) {
    uint16_t index = 0;
    if (!parseApplyIndex(line + 6, &index)) {
      reply("ERR APPLY_ARGS");
      return;
    }
    handleApply(index);
    return;
  }

  if (strncmp(line, "CODEBOOK_BEGIN ", 15) == 0) {
    handleCodebookBegin(line + 15);
    return;
  }

  bool legacyNumeric = true;
  for (char *p = line; *p; p++) {
    if (*p < '0' || *p > '9') {
      legacyNumeric = false;
      break;
    }
  }
  if (legacyNumeric) {
    uint16_t index = 0;
    if (parseApplyIndex(line, &index)) {
      handleApply(index);
      return;
    }
  }

  reply("ERR UNKNOWN_COMMAND");
}

static void pollBinaryUpload() {
  while (Serial.available() > 0) {
    size_t chunk = Serial.readBytes(reinterpret_cast<char *>(uploadBuffer),
                                    min((size_t)Serial.available(), sizeof(uploadBuffer)));
    if (!storeWriteChunk(uploadBuffer, chunk)) {
      storeAbortWrite();
      parserState = STATE_LINE;
      reply("ERR WRITE_FAILED");
      return;
    }

    if (storeWriteComplete()) {
      if (storeFinishWrite()) {
        parserState = STATE_LINE;
        reply("OK VERIFIED");
      } else {
        parserState = STATE_LINE;
        reply("ERR CRC_MISMATCH");
      }
    }
  }
}

void protocolInit() {
  parserState = STATE_LINE;
  lineLength = 0;
}

void protocolApplyIndex(uint16_t index) {
  handleApply(index);
}

void protocolPoll() {
  if (parserState == STATE_BINARY_UPLOAD) {
    pollBinaryUpload();
    return;
  }

  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      lineBuffer[lineLength] = '\0';
      handleLine(lineBuffer);
      lineLength = 0;
      continue;
    }
    if (lineLength + 1 < COMMAND_BUFFER_SIZE) {
      lineBuffer[lineLength++] = c;
    }
  }
}
