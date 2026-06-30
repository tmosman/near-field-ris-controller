#include "shift_driver.h"
#include "config.h"

#include <Arduino.h>

static void pulsePin(int pin) {
  digitalWrite(pin, LOW);
  delayMicroseconds(10);
  digitalWrite(pin, HIGH);
  delayMicroseconds(10);
  digitalWrite(pin, LOW);
}

static void latchMotherboard() {
  pulsePin(SERIAL_CLOCK_PIN_T);
}

// Match Imaging_Empty/Imaging_Empty.ino inputBit() argument order and pin mapping.
static void inputBit(
    int inputValue1_1, int inputValue2_1, int inputValue3_1, int inputValue4_1, int inputValue5_1,
    int inputValue1_2, int inputValue2_2, int inputValue3_2, int inputValue4_2, int inputValue5_2,
    int inputValue1_3, int inputValue2_3, int inputValue3_3, int inputValue4_3, int inputValue5_3,
    int inputValue1_4, int inputValue2_4, int inputValue3_4, int inputValue4_4, int inputValue5_4) {
  digitalWrite(DATA_PINS[0], inputValue1_1);
  digitalWrite(DATA_PINS[1], inputValue2_1);
  digitalWrite(DATA_PINS[2], inputValue3_1);
  digitalWrite(DATA_PINS[3], inputValue4_1);
  digitalWrite(DATA_PINS[4], inputValue5_1);

  digitalWrite(DATA_PINS[5], inputValue1_2);
  digitalWrite(DATA_PINS[6], inputValue2_2);
  digitalWrite(DATA_PINS[7], inputValue3_2);
  digitalWrite(DATA_PINS[8], inputValue4_2);
  digitalWrite(DATA_PINS[9], inputValue5_2);

  digitalWrite(DATA_PINS[10], inputValue1_3);
  digitalWrite(DATA_PINS[11], inputValue2_3);
  digitalWrite(DATA_PINS[12], inputValue3_3);
  digitalWrite(DATA_PINS[13], inputValue4_3);
  digitalWrite(DATA_PINS[14], inputValue5_3);

  digitalWrite(DATA_PINS[15], inputValue1_4);
  digitalWrite(DATA_PINS[16], inputValue2_4);
  digitalWrite(DATA_PINS[17], inputValue3_4);
  digitalWrite(DATA_PINS[18], inputValue4_4);
  digitalWrite(DATA_PINS[19], inputValue5_4);

  pulsePin(SERIAL_CLOCK_PIN_M);
}

void shiftInit() {
  for (int i = 0; i < DATA_PIN_COUNT; i++) {
    pinMode(DATA_PINS[i], OUTPUT);
    digitalWrite(DATA_PINS[i], LOW);
  }
  pinMode(SERIAL_CLOCK_PIN_T, OUTPUT);
  pinMode(SERIAL_CLOCK_PIN_M, OUTPUT);
  pinMode(REGISTER_CLOCK_PIN_T, OUTPUT);
  digitalWrite(SERIAL_CLOCK_PIN_T, LOW);
  digitalWrite(SERIAL_CLOCK_PIN_M, LOW);
  digitalWrite(REGISTER_CLOCK_PIN_T, LOW);
}

// Imaging_Empty.ino clear()
void shiftClear() {
  for (int j = 0; j < 64; j++) {
    for (int i = 0; i < 8; i++) {
      inputBit(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    }
    latchMotherboard();
  }
  pulsePin(REGISTER_CLOCK_PIN_T);
}

// Imaging_Empty.ino outputBits() — loop to 1281, no bounds check on byte index.
void shiftOutputFromBuffer(const uint8_t *maskData, uint16_t maskBytes) {
  uint8_t bits[DATA_PIN_COUNT];

  for (int i = 0; i < (int)maskBytes + 1; i += DATA_PIN_COUNT) {
    for (int j = 0; j < 8; j++) {
      for (int m = 0; m < DATA_PIN_COUNT; m++) {
        uint8_t b = maskData[i + m];
        bits[m] = (b >> (7 - j)) & 1;
      }
      inputBit(
          bits[0], bits[1], bits[2], bits[3], bits[4],
          bits[5], bits[6], bits[7], bits[8], bits[9],
          bits[10], bits[11], bits[12], bits[13], bits[14],
          bits[15], bits[16], bits[17], bits[18], bits[19]);
    }
    latchMotherboard();
  }
  pulsePin(REGISTER_CLOCK_PIN_T);
}
