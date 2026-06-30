#include "config.h"
#include "codebook_store.h"
#include "protocol.h"
#include "shift_driver.h"

#include <Arduino.h>

void setup() {
  // Shift hardware first — before anything that might touch GPIO (e.g. SerialFlash on pin 6).
  shiftInit();
  shiftClear();

  Serial.begin(921600);
  while (!Serial && millis() < 3000) {
  }

  storeInit();

  Serial.println("OK RAM_STORE");
  if (!storeHasCodebook()) {
    Serial.println("WARN NO_CODEBOOK_LOADED");
  }
  Serial.println("OK RIS_FW=3");
  Serial.println("OK BOOT");
  Serial.flush();

  protocolInit();
}

void loop() {
  protocolPoll();
}
